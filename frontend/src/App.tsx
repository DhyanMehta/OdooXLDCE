import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { AdminAnnouncementsPage } from "./features/admin/AdminAnnouncementsPage";
import { AdminEventsPage } from "./features/admin/AdminEventsPage";
import { AdminHomePage } from "./features/admin/AdminHomePage";
import { AdminMailingListPage } from "./features/admin/AdminMailingListPage";
import { AdminMembersPage } from "./features/admin/AdminMembersPage";
import { AdminPlansPage } from "./features/admin/AdminPlansPage";
import { AuditPage } from "./features/admin/AuditPage";
import { CheckInPage } from "./features/admin/CheckInPage";
import { RolesPage } from "./features/admin/RolesPage";
import { AnnouncementsPage } from "./features/announcements/AnnouncementsPage";
import { LoginPage } from "./features/auth/LoginPage";
import { EventDetailPage } from "./features/events/EventDetailPage";
import { EventsPage } from "./features/events/EventsPage";
import { MemberHomePage } from "./features/member/HomePage";
import { MembershipsPage } from "./features/memberships/MembershipsPage";
import { OrderPage } from "./features/orders/OrderPage";
import { ClubPage } from "./features/public/ClubPage";
import { TicketsPage } from "./features/tickets/TicketsPage";
import { AuthProvider } from "./hooks/useAuth";

function Landing() {
  return (
    <section className="hero-block stack">
      <h1>CampusOS</h1>
      <p className="muted">Student organization management for clubs, events, and members.</p>
      <div className="row">
        <a className="btn" href="/clubs/tech-club">
          Open Tech Club
        </a>
        <a className="btn btn--ghost" href="/login">
          Log in
        </a>
      </div>
    </section>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Landing />} />
            <Route path="login" element={<LoginPage />} />
            <Route path="clubs/:slug" element={<ClubPage />} />
            <Route path="events" element={<EventsPage />} />
            <Route path="events/:eventId" element={<EventDetailPage />} />
            <Route path="memberships" element={<MembershipsPage />} />
            <Route path="announcements" element={<AnnouncementsPage />} />
            <Route path="home" element={<MemberHomePage />} />
            <Route path="tickets" element={<TicketsPage />} />
            <Route path="orders/:orderId" element={<OrderPage />} />
            <Route path="admin" element={<AdminHomePage />} />
            <Route path="admin/plans" element={<AdminPlansPage />} />
            <Route path="admin/members" element={<AdminMembersPage />} />
            <Route path="admin/events" element={<AdminEventsPage />} />
            <Route path="admin/check-in" element={<CheckInPage />} />
            <Route path="admin/announcements" element={<AdminAnnouncementsPage />} />
            <Route path="admin/mailing-list" element={<AdminMailingListPage />} />
            <Route path="admin/roles" element={<RolesPage />} />
            <Route path="admin/audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
