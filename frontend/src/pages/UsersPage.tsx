import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import {
  createInvitation,
  createUser,
  listInvitations,
  listUsers,
  resendInvitation,
  revokeInvitation,
  updateUser,
  type CompanyUser,
  type InvitationPage,
  type UserPage,
  type UserRole,
} from "../api/account";
import { isRequestCancelled } from "../api/client";
import { Dialog } from "../components/hierarchy/Dialogs";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  formatDate,
  inputClassName,
  panelClassName,
} from "../components/intelligence/IntelligenceUi";
import { PageHeader } from "../components/ui/PageHeader";
import { useAuth } from "../auth/useAuth";

const LIMIT = 50;

export function UsersPage(): ReactElement {
  const { role: currentRole } = useAuth();
  const [page, setPage] = useState<UserPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [role, setRole] = useState<UserRole | "">("");
  const [status, setStatus] = useState<"" | "active" | "inactive">("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [editing, setEditing] = useState<CompanyUser | null>(null);
  const [invitations, setInvitations] = useState<InvitationPage | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listUsers({
      isActive: status ? status === "active" : undefined,
      offset,
      role: role || undefined,
      signal: controller.signal,
    })
      .then((value) => {
        setPage(value);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(caught instanceof Error ? caught.message : "Users unavailable.");
      });
    return () => controller.abort();
  }, [offset, revision, role, status]);

  useEffect(() => {
    const controller = new AbortController();
    void listInvitations(controller.signal)
      .then(setInvitations)
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(
            caught instanceof Error ? caught.message : "Invitations unavailable.",
          );
      });
    return () => controller.abort();
  }, [revision]);

  return (
    <section>
      <PageHeader
        eyebrow="Tenant administration"
        headingId="users-heading"
        title="Users"
        description="Manage roles and account access for users in your company only."
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              className={secondaryButtonClassName}
              onClick={() => setCreateOpen(true)}
              type="button"
            >
              Add user directly
            </button>
            <button
              className={primaryButtonClassName}
              onClick={() => setInviteOpen(true)}
              type="button"
            >
              Invite teammate
            </button>
          </div>
        }
      />
      {message ? (
        <p
          className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
          role="status"
        >
          {message}
        </p>
      ) : null}
      <div className={`${panelClassName} mt-6 flex flex-wrap gap-4`}>
        <label className="text-sm font-medium text-foreground">
          Role
          <select
            className={inputClassName}
            onChange={(event) => {
              setOffset(0);
              setRole(event.target.value as UserRole | "");
            }}
            value={role}
          >
            <option value="">All roles</option>
            <option value="owner">Owner</option>
            <option value="admin">Admin</option>
            <option value="engineer">Engineer</option>
            <option value="operator">Operator</option>
            <option value="analyst">Analyst</option>
            <option value="viewer">Viewer</option>
          </select>
        </label>
        <label className="text-sm font-medium text-foreground">
          Status
          <select
            className={inputClassName}
            onChange={(event) => {
              setOffset(0);
              setStatus(event.target.value as "" | "active" | "inactive");
            }}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </div>
      {error ? (
        <div className="mt-5">
          <InlineError
            message={error}
            onRetry={() => {
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        </div>
      ) : !page ? (
        <div className="mt-5">
          <LoadingSkeleton label="Loading company users" />
        </div>
      ) : page.items.length === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="No users match"
            description="Adjust the role or status filters, or add a company user."
          />
        </div>
      ) : (
        <div className="mt-5 overflow-x-auto rounded-lg border border-border bg-card">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((user) => (
                <tr className="border-t border-border" key={user.id}>
                  <td className="px-4 py-3 font-medium text-foreground">
                    {user.full_name ? (
                      <>
                        <span className="block">{user.full_name}</span>
                        <span className="block text-xs font-normal text-muted-foreground">
                          {user.email}
                        </span>
                      </>
                    ) : (
                      user.email
                    )}
                  </td>
                  <td className="px-4 py-3">{user.role}</td>
                  <td className="px-4 py-3">
                    <IntelligenceStatus
                      value={user.is_active ? "healthy" : "inactive"}
                    />
                  </td>
                  <td className="px-4 py-3">{formatDate(user.created_at)}</td>
                  <td className="px-4 py-3">
                    <button
                      className="font-semibold text-link"
                      onClick={() => setEditing(user)}
                      type="button"
                    >
                      Manage
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 pb-4">
            <PaginationControls
              limit={LIMIT}
              offset={offset}
              onPageChange={setOffset}
              total={page.total}
            />
          </div>
        </div>
      )}
      <section className={`${panelClassName} mt-6`}>
        <h2 className="text-lg font-semibold text-foreground">Pending invitations</h2>
        {!invitations ? (
          <div className="mt-4">
            <LoadingSkeleton label="Loading pending invitations" />
          </div>
        ) : invitations.items.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">No pending invitations.</p>
        ) : (
          <ul className="mt-4 divide-y divide-border">
            {invitations.items.map((invitation) => (
              <li
                className="flex flex-wrap items-center justify-between gap-3 py-3"
                key={invitation.id}
              >
                <div>
                  <p className="font-medium text-foreground">
                    {invitation.invited_email}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {invitation.role} · expires {formatDate(invitation.expires_at)}
                  </p>
                </div>
                <div className="flex gap-3">
                  <button
                    className="text-sm font-semibold text-link"
                    onClick={() => {
                      void resendInvitation(invitation.id)
                        .then(() => {
                          setMessage("Invitation resent.");
                          setRevision((value) => value + 1);
                        })
                        .catch((caught: unknown) =>
                          setError(
                            caught instanceof Error
                              ? caught.message
                              : "Invitation could not be resent.",
                          ),
                        );
                    }}
                    type="button"
                  >
                    Resend
                  </button>
                  <button
                    className="text-sm font-semibold text-red-700"
                    onClick={() => {
                      void revokeInvitation(invitation.id)
                        .then(() => {
                          setMessage("Invitation revoked.");
                          setRevision((value) => value + 1);
                        })
                        .catch((caught: unknown) =>
                          setError(
                            caught instanceof Error
                              ? caught.message
                              : "Invitation could not be revoked.",
                          ),
                        );
                    }}
                    type="button"
                  >
                    Revoke
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {createOpen ? (
        <CreateUserDialog
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            setMessage("Company user created.");
            setRevision((value) => value + 1);
          }}
        />
      ) : null}
      {inviteOpen ? (
        <InviteUserDialog
          canInviteOwner={currentRole === "owner"}
          onClose={() => setInviteOpen(false)}
          onCreated={() => {
            setInviteOpen(false);
            setMessage("Invitation queued for delivery.");
            setRevision((value) => value + 1);
          }}
        />
      ) : null}
      {editing ? (
        <ManageUserDialog
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            setMessage("User access updated.");
            setRevision((value) => value + 1);
          }}
        />
      ) : null}
    </section>
  );
}

function InviteUserDialog({
  canInviteOwner,
  onClose,
  onCreated,
}: {
  readonly canInviteOwner: boolean;
  readonly onClose: () => void;
  readonly onCreated: () => void;
}): ReactElement {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    void createInvitation({
      email: String(data.get("email")),
      role: String(data.get("role")) as UserRole,
    })
      .then(onCreated)
      .catch((caught: unknown) =>
        setError(
          caught instanceof Error ? caught.message : "Invitation could not be sent.",
        ),
      )
      .finally(() => setBusy(false));
  };
  return (
    <Dialog
      onClose={onClose}
      title="Invite teammate"
      description="The recipient receives a single-use, expiring invitation link."
    >
      <form className="space-y-4" onSubmit={submit}>
        <label className="block text-sm font-medium">
          Email
          <input className={inputClassName} name="email" required type="email" />
        </label>
        <label className="block text-sm font-medium">
          Assigned role
          <select className={inputClassName} defaultValue="viewer" name="role">
            <option value="viewer">Viewer</option>
            <option value="analyst">Analyst</option>
            <option value="operator">Operator</option>
            <option value="engineer">Engineer</option>
            <option value="admin">Admin</option>
            {canInviteOwner ? <option value="owner">Owner</option> : null}
          </select>
        </label>
        {error ? (
          <p className="text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-3">
          <button className={secondaryButtonClassName} onClick={onClose} type="button">
            Cancel
          </button>
          <button className={primaryButtonClassName} disabled={busy} type="submit">
            {busy ? "Sending…" : "Send invitation"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function CreateUserDialog({
  onClose,
  onCreated,
}: {
  readonly onClose: () => void;
  readonly onCreated: () => void;
}): ReactElement {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    void createUser({
      email: String(data.get("email")),
      full_name: String(data.get("fullName")).trim() || undefined,
      password: String(data.get("password")),
      role: String(data.get("role")) as UserRole,
    })
      .then(onCreated)
      .catch((caught: unknown) =>
        setError(
          caught instanceof Error ? caught.message : "User could not be created.",
        ),
      )
      .finally(() => setBusy(false));
  };
  return (
    <Dialog
      onClose={onClose}
      title="Add company user"
      description="The temporary password must be delivered through an approved channel."
    >
      <form className="space-y-4" onSubmit={submit}>
        <label className="block text-sm font-medium">
          Full name
          <input
            className={inputClassName}
            maxLength={160}
            minLength={2}
            name="fullName"
          />
        </label>
        <label className="block text-sm font-medium">
          Email
          <input className={inputClassName} name="email" required type="email" />
        </label>
        <label className="block text-sm font-medium">
          Initial role
          <select className={inputClassName} name="role" defaultValue="operator">
            <option value="operator">Operator</option>
            <option value="viewer">Viewer</option>
            <option value="analyst">Analyst</option>
            <option value="engineer">Engineer</option>
            <option value="admin">Admin</option>
            <option value="owner">Owner</option>
          </select>
        </label>
        <label className="block text-sm font-medium">
          Temporary password
          <input
            className={inputClassName}
            minLength={12}
            name="password"
            required
            type="password"
          />
        </label>
        {error ? (
          <p className="text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-3">
          <button className={secondaryButtonClassName} onClick={onClose} type="button">
            Cancel
          </button>
          <button className={primaryButtonClassName} disabled={busy} type="submit">
            {busy ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ManageUserDialog({
  onClose,
  onSaved,
  user,
}: {
  readonly onClose: () => void;
  readonly onSaved: () => void;
  readonly user: CompanyUser;
}): ReactElement {
  const [role, setRole] = useState(user.role);
  const [active, setActive] = useState(user.is_active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      onClose={onClose}
      title={`Manage ${user.email}`}
      description="Deactivation immediately revokes this user’s refresh sessions."
    >
      <div className="space-y-4">
        <label className="block text-sm font-medium">
          Role
          <select
            className={inputClassName}
            onChange={(event) => setRole(event.target.value as UserRole)}
            value={role}
          >
            <option value="owner">Owner</option>
            <option value="admin">Admin</option>
            <option value="engineer">Engineer</option>
            <option value="operator">Operator</option>
            <option value="analyst">Analyst</option>
            <option value="viewer">Viewer</option>
          </select>
        </label>
        <label className="flex items-center gap-3 text-sm font-medium">
          <input
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
            type="checkbox"
          />
          Account active
        </label>
        {error ? (
          <p className="text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-3">
          <button className={secondaryButtonClassName} onClick={onClose} type="button">
            Cancel
          </button>
          <button
            className={primaryButtonClassName}
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError(null);
              void updateUser(user.id, { is_active: active, role })
                .then(onSaved)
                .catch((caught: unknown) =>
                  setError(
                    caught instanceof Error
                      ? caught.message
                      : "User could not be updated.",
                  ),
                )
                .finally(() => setBusy(false));
            }}
            type="button"
          >
            {busy ? "Saving…" : "Save access"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
