/**
 * Compatibility aliases over generated OpenAPI component schemas.
 * Prefer importing these names from features; regenerate via `npm run gen:api`.
 */
import type { components } from "./openapi";

type Schemas = components["schemas"];

export type User = Schemas["UserOut"];
export type Club = Schemas["ClubOut"];
export type ClubContext = Schemas["ClubContextOut"];
export type Me = Schemas["MeOut"];
export type Plan = Schemas["PlanOut"];
export type Membership = Schemas["MembershipOut"];
export type MemberPerson = Schemas["MemberPersonOut"];
export type MemberPage = Schemas["MemberPageOut"];
export type TicketPrice = Schemas["TicketPriceOut"];
export type TicketType = Schemas["TicketTypeOut"];
export type EventItem = Schemas["EventOut"];
export type AffectedBooking = Schemas["AffectedBookingOut"];
export type EventStatusResult = Schemas["EventStatusOut"];
export type Order = Schemas["OrderOut"];
export type OrderPage = Schemas["OrderPageOut"];
export type Announcement = Schemas["AnnouncementOut"];
export type AnnouncementPage = Schemas["AnnouncementPageOut"];
export type Delivery = Schemas["DeliveryOut"];
export type Subscriber = Schemas["SubscriberOut"];
export type SubscriberPage = Schemas["SubscriberPageOut"];
export type Ticket = Schemas["TicketOut"];
export type CheckInResult = Schemas["CheckInOut"];
export type CheckInListItem = Schemas["CheckInListItem"];
export type AttendeeTicket = Schemas["AttendeeTicketOut"];
export type RoleAssignment = Schemas["RoleAssignmentOut"];
export type RoleOption = Schemas["RoleOut"];
export type DirectoryPerson = Schemas["DirectoryPersonOut"];
export type AuditRow = Schemas["AuditLogOut"];
export type Attendance = Schemas["AttendanceOut"];
export type Health = Schemas["HealthOut"];
export type Message = Schemas["MessageOut"];
