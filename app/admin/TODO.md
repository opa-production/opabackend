# Admin APIs TODO List

This document outlines all the admin APIs that need to be implemented for the car rental platform.

## ✅ Completed

### Authentication
- [x] Admin login (`POST /api/v1/admin/auth/login`)
- [x] Admin logout (`POST /api/v1/admin/auth/logout`)
- [x] Get current admin info (`GET /api/v1/admin/me`)
- [x] Default super admin creation on startup

### User Management
- [x] Add `is_active` field to Host and Client models
- [x] List all hosts (`GET /api/v1/admin/hosts`)
  - Query parameters: `page`, `limit`, `search` (by name/email), `sort_by`, `order`
  - Response: Paginated list of hosts with basic info
- [x] Get host details (`GET /api/v1/admin/hosts/{host_id}`)
  - Response: Full host profile including cars count, payment methods count
- [x] Update host profile (`PUT /api/v1/admin/hosts/{host_id}`)
  - Fields: `full_name`, `email`, `bio`, `mobile_number`, `id_number`
- [x] Deactivate host account (`PUT /api/v1/admin/hosts/{host_id}/deactivate`)
  - Soft delete: Set `is_active` flag to false
- [x] Activate host account (`PUT /api/v1/admin/hosts/{host_id}/activate`)
- [x] Delete host account (`DELETE /api/v1/admin/hosts/{host_id}`)
  - Hard delete: Permanently remove host and all related data
- [x] Get host's cars (`GET /api/v1/admin/hosts/{host_id}/cars`)
- [x] Get host's payment methods (`GET /api/v1/admin/hosts/{host_id}/payment-methods`)
- [x] Get host's feedback (`GET /api/v1/admin/hosts/{host_id}/feedback`)
- [x] List all clients (`GET /api/v1/admin/clients`)
  - Query parameters: `page`, `limit`, `search` (by name/email), `sort_by`, `order`
- [x] Get client details (`GET /api/v1/admin/clients/{client_id}`)
- [x] Update client profile (`PUT /api/v1/admin/clients/{client_id}`)
  - Fields: `full_name`, `email`, `bio`, `fun_fact`, `mobile_number`, `id_number`
- [x] Deactivate client account (`PUT /api/v1/admin/clients/{client_id}/deactivate`)
- [x] Activate client account (`PUT /api/v1/admin/clients/{client_id}/activate`)
- [x] Delete client account (`DELETE /api/v1/admin/clients/{client_id}`)
- [ ] Get client's booking history (`GET /api/v1/admin/clients/{client_id}/bookings`)
  - (When bookings feature is implemented)

---

## 📋 To Be Implemented

---

### 2. Car Management & Verification

#### Car Status Management
- [x] Add `rejection_reason` and `is_hidden` fields to Car model
- [x] List all cars (`GET /api/v1/admin/cars`)
  - Query parameters: `page`, `limit`, `status` (awaiting/verified/denied), `host_id`, `search`, `sort_by`, `order`
- [x] Get car details (`GET /api/v1/admin/cars/{car_id}`)
  - Full car details including host information
- [x] Update car verification status (`PUT /api/v1/admin/cars/{car_id}/status`)
  - Request body: `verification_status` (awaiting/verified/denied)
  - Optional: `rejection_reason` (if denied)
- [x] Bulk update car status (`PUT /api/v1/admin/cars/bulk-status`)
  - Request body: `car_ids` (array), `verification_status`, `rejection_reason`
- [x] Approve car (`PUT /api/v1/admin/cars/{car_id}/approve`)
  - Sets status to "verified"
- [x] Reject car (`PUT /api/v1/admin/cars/{car_id}/reject`)
  - Sets status to "denied", requires `rejection_reason`
- [x] Get cars awaiting verification (`GET /api/v1/admin/cars/awaiting`)
  - Filter: `verification_status = "awaiting"`
- [x] Get verified cars (`GET /api/v1/admin/cars/verified`)
- [x] Get rejected cars (`GET /api/v1/admin/cars/rejected`)

#### Car Content Management
- [x] Edit car details (`PUT /api/v1/admin/cars/{car_id}`)
  - Admin can edit any car field
- [x] Delete car (`DELETE /api/v1/admin/cars/{car_id}`)
  - Permanently remove car listing
- [x] Hide car from public listing (`PUT /api/v1/admin/cars/{car_id}/hide`)
  - Add `is_hidden` flag to Car model
- [x] Show car in public listing (`PUT /api/v1/admin/cars/{car_id}/show`)

---

### 3. Admin Management

#### Admin Account Management
- [x] List all admins (`GET /api/v1/admin/admins`)
  - Query parameters: `page`, `limit`, `role`, `is_active`, `search`, `sort_by`, `order`
  - Super_admin only
- [x] Get admin details (`GET /api/v1/admin/admins/{admin_id}`)
  - Super_admin only
- [x] Create new admin (`POST /api/v1/admin/admins`)
  - Request: `full_name`, `email`, `password`, `password_confirmation`, `role` (admin/moderator), `is_active`
  - Super_admin only, cannot create super_admin via API
- [x] Update admin profile (`PUT /api/v1/admin/admins/{admin_id}`)
  - Fields: `full_name`, `email`, `role`, `is_active`
  - Super_admin only, cannot modify super_admin
- [x] Change admin password (`PUT /api/v1/admin/admins/{admin_id}/password`)
  - Admin can change another admin's password (super_admin only)
  - Cannot change super_admin password
- [x] Deactivate admin (`PUT /api/v1/admin/admins/{admin_id}/deactivate`)
  - Super_admin only, cannot deactivate super_admin or self
- [x] Activate admin (`PUT /api/v1/admin/admins/{admin_id}/activate`)
  - Super_admin only
- [x] Delete admin (`DELETE /api/v1/admin/admins/{admin_id}`)
  - Super_admin only, cannot delete super_admin or self

#### Admin Profile Management
- [x] Update own profile (`PUT /api/v1/admin/profile`)
  - Fields: `full_name`, `email`
  - Any admin can update their own profile
- [x] Change own password (`PUT /api/v1/admin/change-password`)
  - Request: `current_password`, `new_password`, `new_password_confirmation`
  - Any admin can change their own password

---

### 4. Dashboard & Analytics

#### Statistics
- [x] Get dashboard statistics (`GET /api/v1/admin/dashboard/stats`)
  - Response:
    - Total hosts count (active/inactive)
    - Total clients count (active/inactive)
    - Total cars count
    - Cars awaiting verification count
    - Verified cars count
    - Rejected cars count
    - Hidden/visible cars count
    - Total bookings count (when implemented)
    - Active bookings count (when implemented)
    - Revenue statistics (when implemented)
- [x] Get recent activity (`GET /api/v1/admin/dashboard/activity`)
  - Recent registrations, car submissions, status changes
- [x] Get verification queue stats (`GET /api/v1/admin/dashboard/verification-queue`)
  - Count of cars awaiting verification
  - Average verification time
  - Rejection rate

#### Reports
- [ ] Generate hosts report (`GET /api/v1/admin/reports/hosts`)
  - Export: CSV/JSON
  - Filters: date range, status
- [ ] Generate clients report (`GET /api/v1/admin/reports/clients`)
- [ ] Generate cars report (`GET /api/v1/admin/reports/cars`)
- [ ] Generate verification report (`GET /api/v1/admin/reports/verifications`)
  - Shows verification history with timestamps

---

### 5. Feedback & Support Management

#### Feedback Management
- [x] Add `is_flagged` field to Feedback model
- [x] List all feedback (`GET /api/v1/admin/feedback`)
  - Query parameters: `page`, `limit`, `host_id`, `is_flagged`, `sort_by`, `order`
- [x] Get feedback details (`GET /api/v1/admin/feedback/{feedback_id}`)
- [x] Delete feedback (`DELETE /api/v1/admin/feedback/{feedback_id}`)
  - Remove inappropriate feedback
- [x] Flag feedback for review (`PUT /api/v1/admin/feedback/{feedback_id}/flag`)
- [x] Unflag feedback (`PUT /api/v1/admin/feedback/{feedback_id}/unflag`)

#### Support Tickets (Future)
- [ ] List support tickets (`GET /api/v1/admin/support/tickets`)
- [ ] Get ticket details (`GET /api/v1/admin/support/tickets/{ticket_id}`)
- [ ] Update ticket status (`PUT /api/v1/admin/support/tickets/{ticket_id}/status`)
- [ ] Add ticket response (`POST /api/v1/admin/support/tickets/{ticket_id}/response`)

---

### 6. System Settings & Configuration

#### System Configuration
- [ ] Get system settings (`GET /api/v1/admin/settings`)
- [ ] Update system settings (`PUT /api/v1/admin/settings`)
  - Settings: maintenance mode, verification requirements, etc.
- [ ] Get email templates (`GET /api/v1/admin/settings/email-templates`)
- [ ] Update email template (`PUT /api/v1/admin/settings/email-templates/{template_id}`)

#### Notification Management
- [x] Send notification to all hosts (`POST /api/v1/admin/notifications/broadcast-hosts`)
  - Placeholder implementation (ready for integration with notification service)
- [x] Send notification to all clients (`POST /api/v1/admin/notifications/broadcast-clients`)
  - Placeholder implementation (ready for integration with notification service)
- [x] Send notification to specific user (`POST /api/v1/admin/notifications/send`)
  - Placeholder implementation (ready for integration with notification service)

---

### 7. Payment & Financial Management (Future)

#### Payment Methods
- [ ] List all payment methods (`GET /api/v1/admin/payments/methods`)
- [ ] View payment method details (`GET /api/v1/admin/payments/methods/{method_id}`)
- [ ] Remove payment method (`DELETE /api/v1/admin/payments/methods/{method_id}`)

#### Transactions (When implemented)
- [ ] List all transactions (`GET /api/v1/admin/transactions`)
- [ ] Get transaction details (`GET /api/v1/admin/transactions/{transaction_id}`)
- [ ] Refund transaction (`POST /api/v1/admin/transactions/{transaction_id}/refund`)

---

### 8. Booking Management (Future)

#### Bookings
- [ ] List all bookings (`GET /api/v1/admin/bookings`)
- [ ] Get booking details (`GET /api/v1/admin/bookings/{booking_id}`)
- [ ] Update booking status (`PUT /api/v1/admin/bookings/{booking_id}/status`)
- [ ] Cancel booking (`PUT /api/v1/admin/bookings/{booking_id}/cancel`)
- [ ] View booking history (`GET /api/v1/admin/bookings/history`)

---

## 🔐 Security & Permissions

### Role-Based Access Control
- [ ] Implement role checking middleware
  - `super_admin`: Full access to all endpoints
  - `admin`: Access to most endpoints except admin management
  - `moderator`: Limited access (only content moderation)
- [ ] Add permission decorators for endpoints
- [ ] Log admin actions for audit trail

### Audit Logging
- [ ] Create audit log model
- [ ] Log all admin actions (create, update, delete)
- [ ] View audit logs (`GET /api/v1/admin/audit-logs`)
- [ ] Filter audit logs by admin, action, date range

---

## 📝 Notes

- All admin endpoints require authentication via Bearer token
- Admin role must be verified in token (role: "admin")
- Pagination should be consistent across all list endpoints
- Search functionality should support partial matches
- All delete operations should have confirmation or soft delete option
- Consider implementing rate limiting for admin endpoints
- Add request validation and error handling for all endpoints
- Document all endpoints in Swagger/OpenAPI

---

## 🚀 Implementation Priority

### Phase 1 (High Priority)
1. User Management (Hosts & Clients)
2. Car Verification Status Management
3. Dashboard Statistics

### Phase 2 (Medium Priority)
4. Admin Management
5. Feedback Management
6. Reports Generation

### Phase 3 (Lower Priority)
7. System Settings
8. Notification Management
9. Audit Logging
10. Advanced Analytics

---

**Last Updated:** January 15, 2026
