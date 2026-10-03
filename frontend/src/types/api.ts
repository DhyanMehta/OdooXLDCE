export type User = {
  id: string;
  email: string;
  full_name: string;
};

export type Club = {
  id: string;
  slug: string;
  name: string;
  description: string;
};

export type ClubContext = {
  club: Club;
  permissions: string[];
  is_member: boolean;
  has_active_membership: boolean;
};

export type Me = {
  user: User;
  csrf_token: string;
  clubs: ClubContext[];
};

export type Plan = {
  id: string;
  club_id: string;
  name: string;
  description: string;
  dues_amount: string;
  duration_days: number | null;
  fixed_expires_on: string | null;
  is_active: boolean;
};

export type Membership = {
  id: string;
  club_id: string;
  user_id: string;
  plan_id: string;
  starts_at: string;
  ends_at: string;
  status: string;
};

export type TicketPrice = {
  id: string;
  audience: string;
  amount: string;
  is_active: boolean;
};

export type TicketType = {
  id: string;
  name: string;
  description: string;
  prices: TicketPrice[];
};

export type EventItem = {
  id: string;
  club_id: string;
  title: string;
  description: string;
  venue: string;
  starts_at: string;
  ends_at: string;
  capacity: number;
  status: string;
  sales_opens_at: string | null;
  sales_closes_at: string | null;
  ticket_types: TicketType[];
  seats_remaining: number | null;
};

export type Order = {
  id: string;
  club_id: string;
  user_id: string;
  status: string;
  total_amount: string;
  currency: string;
  expires_at: string | null;
  created_at: string;
  items: Array<{
    id: string;
    item_kind: string;
    quantity: number;
    unit_price_snapshot: string;
    title_snapshot: string;
  }>;
  payments: Array<{
    id: string;
    amount: string;
    method: string;
    status: string;
    provider_ref: string | null;
  }>;
};

export type Announcement = {
  id: string;
  club_id: string;
  title: string;
  body: string;
  visibility: string;
  status: string;
  published_at: string | null;
  created_at: string;
};

export type Ticket = {
  id: string;
  event_id: string;
  club_id: string;
  status: string;
  issued_at: string;
  qr_token: string | null;
  event_title?: string | null;
};
