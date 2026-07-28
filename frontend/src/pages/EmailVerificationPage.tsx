import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  getEmailVerificationStatus,
  resendEmailVerification,
  verifyEmail,
} from "../auth/authApi";
import { useAuth } from "../auth/useAuth";

type VerificationState =
  | "already_verified"
  | "expired"
  | "invalid"
  | "pending"
  | "used"
  | "verified"
  | "verifying";

export function EmailVerificationPage(): ReactElement {
  const { isAuthenticated, logout, refreshUser, user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const [state, setState] = useState<VerificationState>(
    token === null ? "pending" : "verifying",
  );
  const [cooldown, setCooldown] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(
      () => setCooldown((current) => Math.max(current - 1, 0)),
      1_000,
    );
    return () => window.clearInterval(timer);
  }, [cooldown]);

  useEffect(() => {
    if (!isAuthenticated || token !== null) return;
    void getEmailVerificationStatus()
      .then((result) => {
        setCooldown(result.resend_available_in_seconds);
        if (result.is_verified) setState("already_verified");
      })
      .catch(() => setMessage("Verification status is temporarily unavailable."));
  }, [isAuthenticated, token]);

  useEffect(() => {
    if (token === null) return;
    let active = true;
    void verifyEmail(token)
      .then(async (result) => {
        if (!active) return;
        setState(result.status);
        setMessage(result.message);
        if (isAuthenticated) await refreshUser();
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 410) setState("expired");
        else if (error instanceof ApiError && error.status === 409) setState("used");
        else setState("invalid");
        setMessage(error instanceof ApiError ? error.message : "Verification failed.");
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated, refreshUser, token]);

  const resend = useCallback(async (): Promise<void> => {
    setResending(true);
    setMessage(null);
    try {
      const result = await resendEmailVerification();
      setCooldown(result.resend_available_in_seconds);
      setMessage(result.message);
      if (result.local_verification_token !== null) {
        window.location.assign(
          `/verify-email?token=${encodeURIComponent(result.local_verification_token)}`,
        );
      }
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Unable to resend email.");
    } finally {
      setResending(false);
    }
  }, []);

  const signOut = useCallback(async (): Promise<void> => {
    await logout();
    navigate("/login", { replace: true });
  }, [logout, navigate]);

  const title = {
    already_verified: "Email already verified",
    expired: "Verification link expired",
    invalid: "Verification link is invalid",
    pending: "Check your inbox",
    used: "Verification link already used",
    verified: "Email verified",
    verifying: "Verifying your email…",
  }[state];

  return (
    <main className="flex min-h-screen items-center justify-center bg-stone-50 px-5 py-10">
      <section className="w-full max-w-lg rounded-xl border border-neutral-200 bg-white p-7 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800">
          FK SOLUTIONS
        </p>
        <h1 className="mt-4 text-2xl font-semibold text-neutral-950">{title}</h1>
        <p className="mt-3 text-sm leading-6 text-neutral-600" role="status">
          {message ??
            (state === "pending"
              ? `We sent a verification link to ${user?.email ?? "your email address"}.`
              : "Please wait while we confirm your verification link.")}
        </p>
        {isAuthenticated && !["verified", "already_verified"].includes(state) ? (
          <button
            className="mt-6 rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            disabled={resending || cooldown > 0}
            onClick={() => void resend()}
            type="button"
          >
            {resending
              ? "Sending…"
              : cooldown > 0
                ? `Resend available in ${cooldown}s`
                : "Resend verification email"}
          </button>
        ) : null}
        <div className="mt-6">
          {isAuthenticated && state !== "verified" && state !== "already_verified" ? (
            <button
              className="text-sm font-semibold text-purple-800 hover:underline"
              onClick={() => void signOut()}
              type="button"
            >
              Sign out and use another account
            </button>
          ) : (
            <Link
              className="text-sm font-semibold text-purple-800 hover:underline"
              to={state === "verified" || state === "already_verified" ? "/" : "/login"}
            >
              {state === "verified" || state === "already_verified"
                ? "Continue to platform"
                : "Return to sign in"}
            </Link>
          )}
        </div>
      </section>
    </main>
  );
}
