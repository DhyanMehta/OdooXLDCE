import { BrowserMultiFormatReader, type IScannerControls } from "@zxing/browser";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, ApiError, formatApiError } from "../../services/api";
import type { AttendeeTicket, CheckInResult } from "../../types/api";

function announce(text: string) {
  // Accessible live region update; vibration/sound are supplements only.
  try {
    if (navigator.vibrate) navigator.vibrate(40);
  } catch {
    /* ignore */
  }
  const utter = window.speechSynthesis ? new SpeechSynthesisUtterance(text) : null;
  if (utter) {
    utter.rate = 1.05;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  }
}

export function CheckInPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const canOverride = hasPermission("manage_events");

  const [eventId, setEventId] = useState("");
  const [token, setToken] = useState("");
  const [lookupQ, setLookupQ] = useState("");
  const [lookupHits, setLookupHits] = useState<AttendeeTicket[]>([]);
  const [result, setResult] = useState<CheckInResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [overrideWindow, setOverrideWindow] = useState(false);
  const [liveMsg, setLiveMsg] = useState("");

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
  const lastTokenRef = useRef<{ value: string; at: number }>({ value: "", at: 0 });
  const busyRef = useRef(false);

  const eventsRes = useAsyncResource(
    clubId && hasPermission("check_in")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/events", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "events")] : [] },
  );

  const events = (eventsRes.data ?? []).filter((e) => e.status === "published");

  useEffect(() => {
    if (!eventId && events[0]) setEventId(events[0].id);
  }, [events, eventId]);

  const attendanceRes = useAsyncResource(
    clubId && eventId && hasPermission("check_in")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/events/{event_id}/attendance", {
            params: { path: { club_id: clubId, event_id: eventId } },
          })
      : null,
    [clubId, eventId],
    { cacheKeys: clubId && eventId ? [clubKey(clubId, `attendance:${eventId}`)] : [] },
  );

  const recentRes = useAsyncResource(
    clubId && eventId && hasPermission("check_in")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/events/{event_id}/check-ins", {
            params: { path: { club_id: clubId, event_id: eventId }, query: { limit: 20 } },
          })
      : null,
    [clubId, eventId],
    { cacheKeys: clubId && eventId ? [clubKey(clubId, `checkins:${eventId}`)] : [] },
  );

  const stopCamera = useCallback(() => {
    controlsRef.current?.stop();
    controlsRef.current = null;
    const video = videoRef.current;
    const stream = video?.srcObject as MediaStream | null;
    stream?.getTracks().forEach((t) => t.stop());
    if (video) video.srcObject = null;
    setScanning(false);
  }, []);

  useEffect(() => () => stopCamera(), [stopCamera]);

  const submitCheckIn = useCallback(
    async (payload: { qr_token?: string; ticket_id?: string }) => {
      if (!clubId || !eventId || busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setError(null);
      setResult(null);
      try {
        const res = await api.post("/api/v1/clubs/{club_id}/events/{event_id}/check-in", {
          params: { path: { club_id: clubId, event_id: eventId } },
          body: { ...payload, override_window: overrideWindow },
        });
        setResult(res);
        setLiveMsg(`Checked in ${res.attendee_name ?? "attendee"}`);
        announce(`Checked in ${res.attendee_name ?? "attendee"}`);
        invalidate(
          clubKey(clubId, `attendance:${eventId}`),
          clubKey(clubId, `checkins:${eventId}`),
        );
        void attendanceRes.reload();
        void recentRes.reload();
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && err.body && typeof err.body === "object") {
          const dup = err.body as CheckInResult;
          setResult({ ...dup, duplicate: true });
          const when = dup.original_checked_in_at
            ? new Date(dup.original_checked_in_at).toLocaleString()
            : "";
          setLiveMsg(`Duplicate. Original check-in ${when}`);
          announce("Already checked in");
        } else {
          setError(formatApiError(err));
          setLiveMsg(formatApiError(err));
        }
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [clubId, eventId, overrideWindow, attendanceRes, recentRes],
  );

  const onDecoded = useCallback(
    (raw: string) => {
      const value = raw.trim();
      if (!value || value.length < 8) return;
      const now = Date.now();
      if (
        lastTokenRef.current.value === value &&
        now - lastTokenRef.current.at < 2500
      ) {
        return;
      }
      lastTokenRef.current = { value, at: now };
      void submitCheckIn({ qr_token: value });
    },
    [submitCheckIn],
  );

  async function startCamera() {
    setCameraError(null);
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Camera API unavailable in this browser. Use manual token entry.");
      return;
    }
    stopCamera();
    try {
      const reader = new BrowserMultiFormatReader();
      const controls = await reader.decodeFromConstraints(
        {
          audio: false,
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
        },
        videoRef.current!,
        (result, _err, ctrl) => {
          controlsRef.current = ctrl;
          if (result) onDecoded(result.getText());
        },
      );
      controlsRef.current = controls;
      setScanning(true);
    } catch (err) {
      const name = err instanceof Error ? err.name : "";
      if (name === "NotAllowedError") {
        setCameraError("Camera permission denied. Allow camera access or enter the token manually.");
      } else if (name === "NotFoundError") {
        setCameraError("No camera found on this device. Use manual token entry.");
      } else {
        setCameraError(
          err instanceof Error
            ? err.message
            : "Could not start camera. Use manual token entry.",
        );
      }
      stopCamera();
    }
  }

  async function onManual(e: FormEvent) {
    e.preventDefault();
    await submitCheckIn({ qr_token: token.trim() });
    setToken("");
  }

  async function onLookup(e: FormEvent) {
    e.preventDefault();
    if (!clubId || !eventId) return;
    setError(null);
    try {
      const hits = await api.get("/api/v1/clubs/{club_id}/events/{event_id}/attendees", {
        params: {
          path: { club_id: clubId, event_id: eventId },
          query: { q: lookupQ.trim() },
        },
      });
      setLookupHits(hits);
      if (!hits.length) setError("No matching tickets for that name/email.");
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("check_in")) return <Feedback tone="danger">Forbidden</Feedback>;

  return (
    <div className="stack checkin-page">
      <div className="hero-block">
        <h1>Check-in</h1>
        <p className="muted">
          Select an event, scan the attendee QR with the camera, or enter the token manually.
          Admission always goes through the same server rules.
        </p>
      </div>

      <div aria-live="polite" className="sr-only">
        {liveMsg}
      </div>

      <PageState
        loading={eventsRes.loading}
        error={eventsRes.error}
        empty={events.length === 0}
        emptyMessage="No events available for check-in."
      >
        <div className="panel form">
          <label>
            Event
            <select
              value={eventId}
              onChange={(e) => {
                setEventId(e.target.value);
                setResult(null);
                setLookupHits([]);
              }}
              required
            >
              {events.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.title} ({ev.status})
                </option>
              ))}
            </select>
          </label>
          {canOverride && (
            <label className="check-row">
              <input
                type="checkbox"
                checked={overrideWindow}
                onChange={(e) => setOverrideWindow(e.target.checked)}
              />
              Override check-in window (manage_events)
            </label>
          )}
        </div>

        <div className="grid-2 checkin-grid">
          <section className="panel stack">
            <h2>Camera</h2>
            <div className="checkin-video-wrap">
              <video ref={videoRef} className="checkin-video" muted playsInline />
              {busy && <div className="checkin-busy">Checking in…</div>}
            </div>
            <div className="row">
              {!scanning ? (
                <button type="button" className="btn" onClick={() => void startCamera()} disabled={!eventId}>
                  Start camera
                </button>
              ) : (
                <button type="button" className="btn btn--ghost" onClick={stopCamera}>
                  Stop camera
                </button>
              )}
            </div>
            {cameraError && <Feedback tone="warn">{cameraError}</Feedback>}
            <p className="muted small">
              Prefers the rear camera when available. Duplicate frames are suppressed while a request
              is in flight.
            </p>
          </section>

          <section className="stack">
            <form className="panel form" onSubmit={onManual}>
              <h2>Manual token</h2>
              <label>
                QR token
                <input
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  minLength={8}
                  required
                  autoComplete="off"
                />
              </label>
              <button className="btn" type="submit" disabled={busy || !eventId}>
                Check in
              </button>
            </form>

            <form className="panel form" onSubmit={onLookup}>
              <h2>Attendee lookup</h2>
              <p className="muted small">
                Search finds tickets. You must select a specific ticket — a name alone never admits.
              </p>
              <label>
                Name or email
                <input value={lookupQ} onChange={(e) => setLookupQ(e.target.value)} required />
              </label>
              <button className="btn btn--ghost" type="submit" disabled={!eventId}>
                Search
              </button>
              {lookupHits.length > 0 && (
                <ul className="checkin-lookup">
                  {lookupHits.map((hit) => (
                    <li key={hit.ticket_id}>
                      <div>
                        <strong>{hit.attendee_name}</strong>
                        <span className="muted small">
                          {" "}
                          {hit.attendee_email} · {hit.ticket_type_name} · {hit.ticket_status}
                          {hit.checked_in ? " · already in" : ""}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="btn"
                        disabled={busy || hit.checked_in || hit.ticket_status !== "valid"}
                        onClick={() => void submitCheckIn({ ticket_id: hit.ticket_id })}
                      >
                        Admit ticket
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </form>
          </section>
        </div>
      </PageState>

      {error && <Feedback tone="danger">{error}</Feedback>}
      {result && (
        <div
          className={`checkin-result ${result.duplicate ? "checkin-result--dup" : "checkin-result--ok"}`}
          role="status"
        >
          <strong>{result.duplicate ? "Already checked in" : "Checked in"}</strong>
          <p>
            {result.attendee_name ?? "Attendee"}
            {result.attendee_email ? ` · ${result.attendee_email}` : ""}
          </p>
          <p className="muted">
            {result.ticket_type_name ?? "Ticket"} · status {result.ticket_status}
          </p>
          {result.duplicate && result.original_checked_in_at && (
            <p>
              Original check-in: {new Date(result.original_checked_in_at).toLocaleString()}
              {result.checked_in_by_name ? ` · by ${result.checked_in_by_name}` : ""}
            </p>
          )}
          {!result.duplicate && (
            <p className="muted small">
              {new Date(result.checked_in_at).toLocaleString()}
              {result.checked_in_by_name ? ` · by ${result.checked_in_by_name}` : ""}
            </p>
          )}
        </div>
      )}

      {attendanceRes.data && (
        <div className="panel">
          <h2>Attendance</h2>
          <p>
            {attendanceRes.data.unique_checkins} / {attendanceRes.data.tickets_issued} (
            {attendanceRes.data.attendance_percentage}%)
          </p>
        </div>
      )}

      {recentRes.data && recentRes.data.length > 0 && (
        <div className="panel">
          <h2>Recent check-ins</h2>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Attendee</th>
                <th>Type</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {recentRes.data.map((row) => (
                <tr key={row.id}>
                  <td>{new Date(row.checked_in_at).toLocaleTimeString()}</td>
                  <td>
                    {row.attendee_name}
                    <div className="muted small">{row.attendee_email}</div>
                  </td>
                  <td>{row.ticket_type_name}</td>
                  <td>{row.checked_in_by_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
