// Builds ONE site for Vercel:  /            -> the Ranu Group company page (index.html)
//                              /snookers/  -> the RANU Snookers booking app (Vite build)
import { execSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";

const APP = "ranu-snookers/frontend";
const run = (cmd) => execSync(cmd, { cwd: APP, stdio: "inherit", env: { ...process.env, VITE_BASE: "/snookers/" } });

if (!existsSync(`${APP}/node_modules`)) run("npm ci --no-audit --no-fund");
run("npm run build");

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/snookers", { recursive: true });

// Company site: everything at the repo root that is not app/tooling (index.html, any images you add later, ...).
const SKIP = new Set(["ranu-snookers", "scripts", "dist", "node_modules", ".git", ".vercel", ".gitignore", "package.json", "package-lock.json", "vercel.json", "render.yaml", "README.md"]);
for (const name of readdirSync(".")) if (!SKIP.has(name)) cpSync(name, `dist/${name}`, { recursive: true });

cpSync(`${APP}/dist`, "dist/snookers", { recursive: true });
console.log("site built -> dist/ (company page at /, app at /snookers/)");
