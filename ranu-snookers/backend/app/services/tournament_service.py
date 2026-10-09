"""Tournaments: registration, knockout brackets (with byes), round-robin groups,
results, automatic advancement and leaderboard."""
from __future__ import annotations

import math
import random
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.models import Tournament, TournamentMatch, TournamentPlayer
from app.models.enums import MatchStatus, TournamentFormat, TournamentStatus
from app.services import customer_service
from app.services.audit import audit
from app.services.common import ensure_branch_access, get_branch


def create(db: Session, actor: Principal, branch_id: uuid.UUID, data: dict) -> Tournament:
    ensure_branch_access(actor, get_branch(db, branch_id), "tournaments.manage")
    t = Tournament(branch_id=branch_id, status=TournamentStatus.REGISTRATION, **data)
    db.add(t)
    db.flush()
    audit(db, actor, "tournament.create", "tournament", t.id, branch_id=branch_id, after=data)
    db.commit()
    return t


def _get(db: Session, tid: uuid.UUID) -> Tournament:
    t = db.get(Tournament, tid)
    if not t:
        raise NotFound("Tournament not found")
    return t


def register_player(db: Session, actor: Principal, tid: uuid.UUID, customer_id: uuid.UUID, seed: int | None = None, fee_paid: bool = False) -> TournamentPlayer:
    t = _get(db, tid)
    ensure_branch_access(actor, get_branch(db, t.branch_id), "tournaments.manage")
    if t.status != TournamentStatus.REGISTRATION:
        raise InvalidState("Registration is closed")
    count = len(db.scalars(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id == t.id)).all())
    if count >= t.max_players:
        raise Conflict("Tournament is full")
    c = customer_service.get_customer(db, actor, customer_id)
    if db.scalar(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id == t.id, TournamentPlayer.customer_id == c.id)):
        raise Conflict("Player already registered")
    p = TournamentPlayer(tournament_id=t.id, customer_id=c.id, display_name=c.name, seed=seed, fee_paid=fee_paid)
    db.add(p)
    db.commit()
    return p


def _seeded_order(players: list[TournamentPlayer]) -> list[TournamentPlayer]:
    seeded = sorted([p for p in players if p.seed], key=lambda p: p.seed)
    rest = [p for p in players if not p.seed]
    random.shuffle(rest)
    return seeded + rest


def _bracket_positions(n: int) -> list[int]:
    """Standard seeding positions so seed 1 and 2 can only meet in the final."""
    pos = [1]
    while len(pos) < n:
        m = len(pos) * 2 + 1
        pos = [x for p in pos for x in (p, m - p)]
    return pos


def start(db: Session, actor: Principal, tid: uuid.UUID) -> Tournament:
    t = _get(db, tid)
    ensure_branch_access(actor, get_branch(db, t.branch_id), "tournaments.manage")
    if t.status != TournamentStatus.REGISTRATION:
        raise InvalidState("Tournament already started")
    players = list(db.scalars(select(TournamentPlayer).where(TournamentPlayer.tournament_id == t.id)).all())
    if len(players) < 2:
        raise ValidationFailed("At least 2 players are required")
    if t.format == TournamentFormat.ROUND_ROBIN:
        _round_robin(db, t, players, group_no=None)
    elif t.format == TournamentFormat.GROUPS_KNOCKOUT:
        groups = max(2, t.group_count or 2)
        ordered = _seeded_order(players)
        for i, p in enumerate(ordered):
            p.group_no = (i % groups) + 1
        for g in range(1, groups + 1):
            _round_robin(db, t, [p for p in ordered if p.group_no == g], group_no=g)
    else:
        _knockout(db, t, _seeded_order(players))
    t.status = TournamentStatus.IN_PROGRESS
    audit(db, actor, "tournament.start", "tournament", t.id, branch_id=t.branch_id, after={"players": len(players), "format": t.format})
    db.commit()
    return t


def _round_robin(db: Session, t: Tournament, players: list[TournamentPlayer], group_no: int | None) -> None:
    ps: list[TournamentPlayer | None] = list(players)
    if len(ps) % 2:
        ps.append(None)
    n = len(ps)
    stage = "GROUP" if group_no else "RR"
    base = (group_no or 0) * 1000
    for rnd in range(n - 1):
        for i in range(n // 2):
            a, b = ps[i], ps[n - 1 - i]
            if a and b:
                db.add(TournamentMatch(tournament_id=t.id, stage=stage, round_no=rnd + 1, match_no=base + i + 1, group_no=group_no,
                                       player1_id=a.id, player2_id=b.id, status=MatchStatus.SCHEDULED))
        ps = [ps[0]] + [ps[-1]] + ps[1:-1]


def _knockout(db: Session, t: Tournament, ordered: list[TournamentPlayer], stage: str = "KO") -> None:
    size = 2 ** math.ceil(math.log2(len(ordered)))
    rounds = int(math.log2(size))
    slots: list[TournamentPlayer | None] = [None] * size
    for idx, pos in enumerate(_bracket_positions(size)):
        slots[idx] = ordered[pos - 1] if pos - 1 < len(ordered) else None
    matches: dict[tuple[int, int], TournamentMatch] = {}
    for r in range(rounds, 0, -1):  # create later rounds first so we can link next_match_id
        count = size // (2 ** r)
        for m in range(count):
            mt = TournamentMatch(tournament_id=t.id, stage=stage, round_no=r, match_no=m + 1, status=MatchStatus.PENDING)
            if r < rounds:
                nxt = matches[(r + 1, m // 2)]
                mt.next_match_id, mt.next_slot = nxt.id, (m % 2) + 1
            db.add(mt)
            db.flush()
            matches[(r, m)] = mt
    for m in range(size // 2):
        mt = matches[(1, m)]
        a, b = slots[2 * m], slots[2 * m + 1]
        mt.player1_id, mt.player2_id = (a.id if a else None), (b.id if b else None)
        mt.status = MatchStatus.SCHEDULED
        if a is None or b is None:  # bye
            winner = a or b
            mt.status, mt.winner_id = MatchStatus.WALKOVER, (winner.id if winner else None)
            if winner:
                _advance(db, mt, winner.id)


def _advance(db: Session, mt: TournamentMatch, winner_id: uuid.UUID) -> None:
    if not mt.next_match_id:
        return
    nxt = db.get(TournamentMatch, mt.next_match_id)
    if mt.next_slot == 1:
        nxt.player1_id = winner_id
    else:
        nxt.player2_id = winner_id
    if nxt.player1_id and nxt.player2_id:
        nxt.status = MatchStatus.SCHEDULED


def record_result(db: Session, actor: Principal, match_id: uuid.UUID, score1: int, score2: int, table_id: uuid.UUID | None = None) -> TournamentMatch:
    mt = db.get(TournamentMatch, match_id)
    if not mt:
        raise NotFound("Match not found")
    t = _get(db, mt.tournament_id)
    ensure_branch_access(actor, get_branch(db, t.branch_id), "tournaments.manage")
    if mt.status in (MatchStatus.COMPLETED, MatchStatus.WALKOVER):
        raise InvalidState("Result already recorded")
    if not (mt.player1_id and mt.player2_id):
        raise InvalidState("Both players are not known yet")
    if score1 == score2 and mt.stage == "KO":
        raise ValidationFailed("Knockout matches need a winner")
    mt.score1, mt.score2, mt.table_id = score1, score2, table_id or mt.table_id
    mt.status = MatchStatus.COMPLETED
    p1, p2 = db.get(TournamentPlayer, mt.player1_id), db.get(TournamentPlayer, mt.player2_id)
    p1.frames_for += score1
    p1.frames_against += score2
    p2.frames_for += score2
    p2.frames_against += score1
    if score1 != score2:
        win, lose = (p1, p2) if score1 > score2 else (p2, p1)
        mt.winner_id = win.id
        win.wins += 1
        lose.losses += 1
        if mt.stage == "KO":
            lose.eliminated = True
            _advance(db, mt, win.id)
            if not mt.next_match_id:
                t.winner_player_id = win.id
                t.status = TournamentStatus.COMPLETED
    audit(db, actor, "tournament.result", "tournament_match", mt.id, branch_id=t.branch_id, after={"score": f"{score1}-{score2}"})
    db.flush()
    _maybe_finish_groups(db, t)
    db.commit()
    return mt


def _maybe_finish_groups(db: Session, t: Tournament) -> None:
    matches = db.scalars(select(TournamentMatch).where(TournamentMatch.tournament_id == t.id)).all()
    group = [m for m in matches if m.stage in ("GROUP", "RR")]
    if not group or any(m.status not in (MatchStatus.COMPLETED, MatchStatus.WALKOVER) for m in group):
        return
    if t.format == TournamentFormat.ROUND_ROBIN and t.status != TournamentStatus.COMPLETED:
        board = leaderboard(db, t.id)
        t.winner_player_id = board[0]["player_id"] if board else None
        t.status = TournamentStatus.COMPLETED
    elif t.format == TournamentFormat.GROUPS_KNOCKOUT and not any(m.stage == "KO" for m in matches):
        qualifiers: list[TournamentPlayer] = []
        for g in sorted({m.group_no for m in group}):
            rows = [r for r in leaderboard(db, t.id) if r["group_no"] == g][:2]
            qualifiers += [db.get(TournamentPlayer, r["player_id"]) for r in rows]
        _knockout(db, t, qualifiers)


def leaderboard(db: Session, tid: uuid.UUID) -> list[dict]:
    players = db.scalars(select(TournamentPlayer).where(TournamentPlayer.tournament_id == tid)).all()
    rows = [{"player_id": p.id, "name": p.display_name, "group_no": p.group_no, "wins": p.wins, "losses": p.losses, "frames_for": p.frames_for,
             "frames_against": p.frames_against, "frame_diff": p.frames_for - p.frames_against, "points": p.wins * 2, "eliminated": p.eliminated} for p in players]
    return sorted(rows, key=lambda r: (-r["points"], -r["frame_diff"], -r["frames_for"], r["name"]))


def detail(db: Session, tid: uuid.UUID) -> dict:
    t = _get(db, tid)
    players = db.scalars(select(TournamentPlayer).where(TournamentPlayer.tournament_id == tid)).all()
    matches = db.scalars(select(TournamentMatch).where(TournamentMatch.tournament_id == tid).order_by(TournamentMatch.stage, TournamentMatch.round_no, TournamentMatch.match_no)).all()
    return {"tournament": t, "players": list(players), "matches": list(matches), "leaderboard": leaderboard(db, tid)}


def list_for_branch(db: Session, branch_id: uuid.UUID) -> list[Tournament]:
    return list(db.scalars(select(Tournament).where(Tournament.branch_id == branch_id).order_by(Tournament.created_at.desc())).all())
