import { useAuth } from "@/stores/auth";

/** Current branch id (admin screens only render once a branch is known). */
export function useBranchId(): string {
  const { branch } = useAuth();
  return branch?.id ?? "";
}
