import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  getEmailVerificationStatus,
  resendEmailVerification,
  verifyEmail,
} from "../auth/authApi";
import { useAuth } from "../auth/useAuth";
import {
  AuthHeader,
  AuthMessage,
  AuthShell,
  LoadingSpinner,
  authLinkClassName,
  authPrimaryButtonClassName,
  authSecondaryButtonClassName,
} from "../components/auth/AuthUi";

type VerificationState =
  | "already_verified"
  | "expired"
  | "invalid"
  | "pending"
  | "used"
  | "verified"
  | "verifying";

const copy: Record<
  VerificationState,
  { eyebrow: string; title: string; description: string }
> = {
  already_verified: {
    eyebrow: "Email confirmed",
    title: "Your email is already verified",
    description: "Your account is ready. Continue to your FactoryMind workspace.",
  },
  expired: {
    eyebrow: "Verification link",
    title: "This verification link has expired",
    description:
      "Verification links expire to protect your account. Sign in to request a fresh link.",
  },
  invalid: {
    eyebrow: "Verification link",
    title: "This verification link is not valid",
    description:
      "The link may be incomplete or no longer recognized. Sign in to request a fresh link.",
  },
  pending: {
    eyebrow: "One last step",
    title: "Check your inbox",
    description:
      "Use the secure link we sent to confirm your work email and activate your workspace.",
  },
  used: {
    eyebrow: "Verification link",
    title: "This verification link was already used",
    description:
      "Try signing in. If verification is still required, you can request a fresh link.",
  },
  verified: {
    eyebrow: "Email confirmed",
    title: "Your email is verified",
    description: "Your FactoryMind workspace is ready for you.",
  },
  verifying: {
    eyebrow: "Secure verification",
    title: "Confirming your email…",
    description: "Keep this page open while we securely validate your link.",
  },
};

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
  const resendingRef = useRef(false);

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
      .catch(() =>
        setMessage(
          "Verification status is temporarily unavailable. You can safely try again.",
        ),
      );
  }, [isAuthenticated, token]);

  useEffect(() => {
    if (token === null) return;
    let active = true;
    void verifyEmail(token)
      .then(async (result) => {
        if (!active) return;
        setState(result.status);
        setMessage(null);
        if (isAuthenticated) await refreshUser();
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 410) setState("expired");
        else if (error instanceof ApiError && error.status === 409) setState("used");
        else setState("invalid");
        setMessage(null);
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated, refreshUser, token]);

  const resend = useCallback(async (): Promise<void> => {
    if (resendingRef.current || cooldown > 0) return;
    resendingRef.current = true;
    setResending(true);
    setMessage(null);
    try {
      const result = await resendEmailVerification();
      setCooldown(result.resend_available_in_seconds);
      setMessage(
        "A fresh verification link has been queued. Check your inbox and spam folder.",
      );
      if (result.local_verification_token !== null) {
        window.location.assign(
          `/verify-email?token=${encodeURIComponent(result.local_verification_token)}`,
        );
      }
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.status === 429
          ? "Please wait before requesting another verification email."
          : "We could not resend the email. Check your connection and try again.",
      );
    } finally {
      resendingRef.current = false;
      setResending(false);
    }
  }, [cooldown]);

  const signOut = useCallback(async (): Promise<void> => {
    await logout();
    navigate("/login", { replace: true });
  }, [logout, navigate]);

  const successful = state === "verified" || state === "already_verified";
  const recoverable = state === "expired" || state === "invalid" || state === "used";

  return (
    <AuthShell compact>
      <AuthHeader {...copy[state]} />
      {state === "verifying" ? (
        <div
          aria-label="Verifying email"
          className="mt-7 flex justify-center text-[var(--primary-action)]"
          role="status"
        >
          <span className="scale-125">
            <LoadingSpinner />
          </span>
        </div>
      ) : null}
      {state === "pending" && user?.email ? (
        <AuthMessage>
          Sent to <strong>{user.email}</strong>. The link expires in 24 hours.
        </AuthMessage>
      ) : null}
      {message ? (
        <AuthMessage tone={message.startsWith("A fresh") ? "success" : "danger"}>
          {message}
        </AuthMessage>
      ) : null}

      {isAuthenticated && !successful && state !== "verifying" ? (
        <button
          className={`${authPrimaryButtonClassName} mt-7`}
          disabled={resending || cooldown > 0}
          onClick={() => void resend()}
          type="button"
        >
          {resending ? <LoadingSpinner /> : null}
          {resending
            ? "Sending secure link…"
            : cooldown > 0
              ? `Resend available in ${cooldown}s`
              : "Resend verification email"}
        </button>
      ) : null}

      {successful ? (
        <Link className={`${authPrimaryButtonClassName} mt-7`} to="/">
          Continue to workspace
        </Link>
      ) : recoverable && !isAuthenticated ? (
        <Link className={`${authPrimaryButtonClassName} mt-7`} to="/login">
          Sign in to request a new link
        </Link>
      ) : null}

      {isAuthenticated && !successful ? (
        <button
          className={`${authSecondaryButtonClassName} mt-3 w-full`}
          onClick={() => void signOut()}
          type="button"
        >
          Sign out and use another account
        </button>
      ) : !successful && state !== "verifying" ? (
        <Link className={`mt-5 inline-block text-sm ${authLinkClassName}`} to="/login">
          Return to sign in
        </Link>
      ) : null}
    </AuthShell>
  );
}
