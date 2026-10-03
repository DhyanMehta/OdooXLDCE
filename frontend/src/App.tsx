import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { AdminAnnouncementsPage } from "./features/admin/AdminAnnouncementsPage";
import { AdminDuesPage } from "./features/admin/AdminDuesPage";
import { AdminEventsPage } from "./features/admin/AdminEventsPage";
import { AdminHomePage } from "./features/admin/AdminHomePage";
import { AdminMailingListPage } from "./features/admin/AdminMailingListPage";
import { AdminMembersPage } from "./features/admin/AdminMembersPage";
import { AdminMerchandisePage } from "./features/admin/AdminMerchandisePage";
import { AdminPlansPage } from "./features/admin/AdminPlansPage";
import { AdminExpenseReviewPage } from "./features/admin/AdminExpenseReviewPage";
import { AdminFinancePage } from "./features/admin/AdminFinancePage";
import { AdminProjectsPage } from "./features/admin/AdminProjectsPage";
import { AdminRefundsPage } from "./features/admin/AdminRefundsPage";
import { AuditPage } from "./features/admin/AuditPage";
import { CheckInPage } from "./features/admin/CheckInPage";
import { RolesPage } from "./features/admin/RolesPage";
import { AnnouncementDetailPage } from "./features/announcements/AnnouncementDetailPage";
import { AnnouncementsPage } from "./features/announcements/AnnouncementsPage";
import { LoginPage } from "./features/auth/LoginPage";
import { ProfilePage } from "./features/auth/ProfilePage";
import { EventDetailPage } from "./features/events/EventDetailPage";
import { EventsPage } from "./features/events/EventsPage";
import { ConfirmPage } from "./features/mailing/ConfirmPage";
import { UnsubscribePage } from "./features/mailing/UnsubscribePage";
import { MemberHomePage } from "./features/member/HomePage";
import { MerchandisePage } from "./features/merchandise/MerchandisePage";
import { MyMerchandisePage } from "./features/merchandise/MyMerchandisePage";
import { ExpensesPage } from "./features/finance/ExpensesPage";
import { MyRefundsPage } from "./features/finance/MyRefundsPage";
import { MembershipsPage } from "./features/memberships/MembershipsPage";
import { MyAssignmentsPage } from "./features/projects/MyAssignmentsPage";
import { ProjectsPage } from "./features/projects/ProjectsPage";
import { OrderPage } from "./features/orders/OrderPage";
import { OrdersPage } from "./features/orders/OrdersPage";
import { ClubPage } from "./features/public/ClubPage";
import { ClubsDirectoryPage } from "./features/public/ClubsDirectoryPage";
import { TicketsPage } from "./features/tickets/TicketsPage";
import { AuthProvider } from "./hooks/useAuth";

function Landing() {
  return (
    <section className="hero-block stack">
      <h1>CampusOS</h1>
      <p className="muted">Student organization management for clubs, events, and members.</p>
      <div className="row">
        <a className="btn" href="/clubs">
          Browse clubs
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
            <Route path="profile" element={<ProfilePage />} />
            <Route path="clubs" element={<ClubsDirectoryPage />} />
            <Route path="clubs/:slug" element={<ClubPage />} />
            <Route path="events" element={<EventsPage />} />
            <Route path="events/:eventId" element={<EventDetailPage />} />
            <Route path="memberships" element={<MembershipsPage />} />
            <Route path="shop" element={<MerchandisePage />} />
            <Route path="my-merch" element={<MyMerchandisePage />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="my-assignments" element={<MyAssignmentsPage />} />
            <Route path="announcements" element={<AnnouncementsPage />} />
            <Route path="announcements/:announcementId" element={<AnnouncementDetailPage />} />
            <Route path="mailing/confirm" element={<ConfirmPage />} />
            <Route path="mailing/unsubscribe" element={<UnsubscribePage />} />
            <Route path="home" element={<MemberHomePage />} />
            <Route path="tickets" element={<TicketsPage />} />
            <Route path="orders" element={<OrdersPage />} />
            <Route path="orders/:orderId" element={<OrderPage />} />
            <Route path="expenses" element={<ExpensesPage />} />
            <Route path="my-refunds" element={<MyRefundsPage />} />
            <Route path="admin" element={<AdminHomePage />} />
            <Route path="admin/plans" element={<AdminPlansPage />} />
            <Route path="admin/members" element={<AdminMembersPage />} />
            <Route path="admin/dues" element={<AdminDuesPage />} />
            <Route path="admin/events" element={<AdminEventsPage />} />
            <Route path="admin/check-in" element={<CheckInPage />} />
            <Route path="admin/announcements" element={<AdminAnnouncementsPage />} />
            <Route path="admin/mailing-list" element={<AdminMailingListPage />} />
            <Route path="admin/roles" element={<RolesPage />} />
            <Route path="admin/audit" element={<AuditPage />} />
            <Route path="admin/merchandise" element={<AdminMerchandisePage />} />
            <Route path="admin/projects" element={<AdminProjectsPage />} />
            <Route path="admin/expenses" element={<AdminExpenseReviewPage />} />
            <Route path="admin/refunds" element={<AdminRefundsPage />} />
            <Route path="admin/finance" element={<AdminFinancePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
