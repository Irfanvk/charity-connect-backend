# CharityConnect API JSON Schemas & TypeScript Interfaces

This document provides complete TypeScript interfaces and JSON schemas for all API request/response objects.

---

## TypeScript Interfaces

### Enums

```typescript
// User Roles
export enum UserRole {
  SUPERADMIN = 'superadmin',
  ADMIN = 'admin',
  MEMBER = 'member'
}

// Challan Status
export enum ChallanStatus {
  GENERATED = 'generated',
  PENDING = 'pending',
  APPROVED = 'approved',
  REJECTED = 'rejected'
}

// Challan Type
export enum ChallanType {
  MONTHLY = 'monthly',
  CAMPAIGN = 'campaign'
}
```

---

## Authentication Schemas

### UserLogin (Request)
```typescript
interface UserLogin {
  username?: string;  // Optional if email provided
  email?: string;     // Optional if username provided
  password: string;   // Required
}
```

**JSON Example:**
```json
{
  "email": "user@example.com",
  "password": "securePassword123"
}
```

---

### UserRegisterWithInvite (Request)
```typescript
interface UserRegisterWithInvite {
  invite_code: string;       // Required
  username: string;          // Required
  password: string;          // Required
  full_name?: string;        // Optional
  email?: string;            // Optional
  phone?: string;            // Required if email not provided
  address?: string;          // Optional
  monthly_amount?: number;   // Optional, default: 0.0
}
```

**JSON Example:**
```json
{
  "invite_code": "INV-ABC123",
  "username": "john_doe",
  "password": "securePassword123",
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "address": "123 Main St, City, Country",
  "monthly_amount": 500.0
}
```

---

### UserResponse
```typescript
interface UserResponse {
  id: number;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;  // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 1,
  "username": "john_doe",
  "full_name": "john_doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "role": "member",
  "is_active": true,
  "created_at": "2026-03-01T10:00:00"
}
```

---

### TokenResponse
```typescript
interface TokenResponse {
  access_token: string;
  token_type: string;  // Always "bearer"
  user: UserResponse;
}
```

**JSON Example:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6Im1lbWJlciIsImV4cCI6MTcwOTU1MDAwMH0.signature",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "john_doe",
    "full_name": "john_doe",
    "email": "john@example.com",
    "phone": "+1234567890",
    "role": "member",
    "is_active": true,
    "created_at": "2026-03-01T10:00:00"
  }
}
```

---

## Member Schemas

### MemberCreate (Request)
```typescript
interface MemberCreate {
  user_id: number;
  member_code: string;
  monthly_amount?: number;  // Default: 0.0
  address?: string;
}
```

---

### MemberUpdate (Request)
```typescript
interface MemberUpdate {
  monthly_amount?: number;
  address?: string;
  status?: string;  // e.g., "active", "inactive", "suspended"
}
```

**JSON Example:**
```json
{
  "monthly_amount": 600.0,
  "address": "456 New Address",
  "status": "active"
}
```

---

### MemberResponse
```typescript
interface MemberResponse {
  id: number;
  user_id: number;
  full_name: string | null;
  member_code: string;
  monthly_amount: number;
  address: string | null;
  join_date: string;    // ISO 8601 datetime
  status: string;       // "active", "inactive", "suspended"
  created_at: string;   // ISO 8601 datetime
  updated_at: string;   // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 1,
  "user_id": 5,
  "full_name": "john_doe",
  "member_code": "MEM-2026-001",
  "monthly_amount": 500.0,
  "address": "123 Main St, City",
  "join_date": "2026-01-15T10:00:00",
  "status": "active",
  "created_at": "2026-01-15T10:00:00",
  "updated_at": "2026-03-01T12:00:00"
}
```

---

## Invite Schemas

### InviteCreate (Request)
```typescript
interface InviteCreate {
  email?: string;
  phone?: string;
  expiry_date?: string;   // ISO 8601 datetime
  expires_at?: string;    // Alternative field for expiry_date
}
```

**JSON Example:**
```json
{
  "email": "newuser@example.com",
  "phone": "+1234567890",
  "expiry_date": "2026-04-01T23:59:59"
}
```

---

### InviteUpdate (Request)
```typescript
interface InviteUpdate {
  email?: string;
  phone?: string;
  expiry_date?: string;   // ISO 8601 datetime
  expires_at?: string;    // Alternative field
}
```

---

### InviteResponse
```typescript
interface InviteResponse {
  id: number;
  invite_code: string;
  email: string | null;
  phone: string | null;
  is_used: boolean;
  expiry_date: string;    // ISO 8601 datetime
  created_at: string;     // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 5,
  "invite_code": "INV-XYZ789",
  "email": "newuser@example.com",
  "phone": "+1234567890",
  "is_used": false,
  "expiry_date": "2026-04-01T23:59:59",
  "created_at": "2026-03-03T10:00:00"
}
```

---

### InviteValidate (Request)
```typescript
interface InviteValidate {
  invite_code: string;
  email_or_phone: string;
}
```

**JSON Example:**
```json
{
  "invite_code": "INV-XYZ789",
  "email_or_phone": "user@example.com"
}
```

---

## Campaign Schemas

### CampaignCreate (Request)
```typescript
interface CampaignCreate {
  title: string;
  description?: string;
  target_amount: number;
  start_date: string;     // ISO 8601 datetime
  end_date: string;       // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "title": "Ramadan Food Drive 2026",
  "description": "Providing food packages for families in need during Ramadan",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59"
}
```

---

### CampaignUpdate (Request)
```typescript
interface CampaignUpdate {
  title?: string;
  description?: string;
  target_amount?: number;
  start_date?: string;    // ISO 8601 datetime
  end_date?: string;      // ISO 8601 datetime
  is_active?: boolean;
}
```

**JSON Example:**
```json
{
  "title": "Updated Campaign Title",
  "target_amount": 60000.0,
  "is_active": false
}
```

---

### CampaignResponse
```typescript
interface CampaignResponse {
  id: number;
  title: string;
  description: string | null;
  target_amount: number;
  start_date: string;     // ISO 8601 datetime
  end_date: string;       // ISO 8601 datetime
  is_active: boolean;
  created_at: string;     // ISO 8601 datetime
  updated_at: string;     // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 3,
  "title": "Ramadan Food Drive 2026",
  "description": "Providing food packages for families in need during Ramadan",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59",
  "is_active": true,
  "created_at": "2026-03-03T10:00:00",
  "updated_at": "2026-03-03T10:00:00"
}
```

---

## Challan Schemas

### ChallanCreate (Request)
```typescript
interface ChallanCreate {
  member_id?: number;         // Optional for members, required for admin
  type: ChallanType;          // "monthly" or "campaign"
  month?: string;             // YYYY-MM format, required for monthly type
  campaign_id?: number;       // Required for campaign type
  amount: number;
  payment_method?: string;    // e.g., "cash", "bank_transfer", "online"
}
```

**JSON Example (Monthly):**
```json
{
  "type": "monthly",
  "month": "2026-03",
  "amount": 500.0,
  "payment_method": "bank_transfer"
}
```

**JSON Example (Campaign):**
```json
{
  "type": "campaign",
  "campaign_id": 3,
  "amount": 1000.0,
  "payment_method": "online"
}
```

---

### ChallanApprove (Request)
```typescript
interface ChallanApprove {
  approved_by_admin_id: number;
}
```

**JSON Example:**
```json
{
  "approved_by_admin_id": 2
}
```

---

### ChallanReject (Request)
```typescript
interface ChallanReject {
  rejection_reason: string;
}
```

**JSON Example:**
```json
{
  "rejection_reason": "Invalid payment proof or amount mismatch"
}
```

---

### ChallanResponse
```typescript
interface ChallanResponse {
  id: number;
  member_id: number;
  type: ChallanType;
  month: string | null;           // YYYY-MM format
  campaign_id: number | null;
  amount: number;
  payment_method: string | null;
  proof_path: string | null;
  status: ChallanStatus;
  created_at: string;             // ISO 8601 datetime
  proof_uploaded_at: string | null;   // ISO 8601 datetime
  approved_at: string | null;         // ISO 8601 datetime
  updated_at: string;                 // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 10,
  "member_id": 1,
  "type": "monthly",
  "month": "2026-03",
  "campaign_id": null,
  "amount": 500.0,
  "payment_method": "bank_transfer",
  "proof_path": "/uploads/proofs/abc123.jpg",
  "status": "approved",
  "created_at": "2026-03-03T10:00:00",
  "proof_uploaded_at": "2026-03-03T11:30:00",
  "approved_at": "2026-03-04T09:00:00",
  "updated_at": "2026-03-04T09:00:00"
}
```

---

## Notification Schemas

### NotificationCreate (Request)
```typescript
interface NotificationCreate {
  user_id?: number;         // Send to specific user
  title: string;
  message: string;
  target_role?: UserRole;   // Send to all users with this role
}
```

**JSON Example (Single User):**
```json
{
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your March 2026 payment has been approved."
}
```

**JSON Example (Role Broadcast):**
```json
{
  "target_role": "member",
  "title": "Monthly Reminder",
  "message": "Please submit your monthly donation for March 2026."
}
```

**JSON Example (All Users):**
```json
{
  "title": "System Maintenance",
  "message": "The system will be under maintenance on Sunday."
}
```

---

### NotificationUpdate (Request)
```typescript
interface NotificationUpdate {
  is_read: boolean;
}
```

---

### NotificationAdminUpdate (Request)
```typescript
interface NotificationAdminUpdate {
  title?: string;
  message?: string;
  is_read?: boolean;
}
```

---

### NotificationResponse
```typescript
interface NotificationResponse {
  id: number;
  user_id: number;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;       // ISO 8601 datetime
  read_at: string | null;   // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 25,
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your March 2026 payment has been approved.",
  "is_read": false,
  "created_at": "2026-03-04T09:00:00",
  "read_at": null
}
```

---

## Audit Log Schemas

### AuditLogCreate (Request)
```typescript
interface AuditLogCreate {
  user_id?: number;
  action: string;           // e.g., "create", "update", "delete", "approve"
  entity_type: string;      // e.g., "Member", "Challan", "Campaign"
  entity_id: number;
  old_values?: string;      // JSON string
  new_values?: string;      // JSON string
  ip_address?: string;
}
```

**JSON Example:**
```json
{
  "user_id": 2,
  "action": "approve",
  "entity_type": "Challan",
  "entity_id": 10,
  "old_values": "{\"status\": \"pending\"}",
  "new_values": "{\"status\": \"approved\", \"approved_at\": \"2026-03-04T09:00:00\"}",
  "ip_address": "192.168.1.100"
}
```

---

### AuditLogResponse
```typescript
interface AuditLogResponse {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: number;
  old_values: string | null;    // JSON string
  new_values: string | null;    // JSON string
  ip_address: string | null;
  created_at: string;           // ISO 8601 datetime
}
```

**JSON Example:**
```json
{
  "id": 150,
  "user_id": 2,
  "action": "approve",
  "entity_type": "Challan",
  "entity_id": 10,
  "old_values": "{\"status\": \"pending\"}",
  "new_values": "{\"status\": \"approved\", \"approved_at\": \"2026-03-04T09:00:00\"}",
  "ip_address": "192.168.1.100",
  "created_at": "2026-03-04T09:00:00"
}
```

---

## File Upload Schemas

### FileUploadResponse
```typescript
interface FileUploadResponse {
  file_url: string;     // Relative path
  filename: string;     // UUID-based filename
}
```

**JSON Example:**
```json
{
  "file_url": "/uploads/proofs/550e8400-e29b-41d4-a716-446655440000.jpg",
  "filename": "550e8400-e29b-41d4-a716-446655440000.jpg"
}
```

---

## Error Response Schemas

### ErrorDetail
```typescript
interface ErrorDetail {
  type: string;         // e.g., "validation_error", "http_error", "server_error"
  loc: string[];        // Location of error, e.g., ["body", "email"]
  msg: string;          // Error message
  input: any;           // User-provided input (may be null)
}
```

---

### ErrorResponse
```typescript
interface ErrorResponse {
  detail: ErrorDetail[];
}
```

**JSON Example (Validation Error):**
```json
{
  "detail": [
    {
      "type": "validation_error",
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "input": "invalid-email"
    },
    {
      "type": "validation_error",
      "loc": ["body", "password"],
      "msg": "field required",
      "input": null
    }
  ]
}
```

**JSON Example (Auth Error):**
```json
{
  "detail": [
    {
      "type": "http_error",
      "loc": ["request"],
      "msg": "Could not validate credentials",
      "input": null
    }
  ]
}
```

---

## Complete TypeScript Definitions File

```typescript
// types.ts - Complete type definitions for CharityConnect API

// ==================== ENUMS ====================

export enum UserRole {
  SUPERADMIN = 'superadmin',
  ADMIN = 'admin',
  MEMBER = 'member'
}

export enum ChallanStatus {
  GENERATED = 'generated',
  PENDING = 'pending',
  APPROVED = 'approved',
  REJECTED = 'rejected'
}

export enum ChallanType {
  MONTHLY = 'monthly',
  CAMPAIGN = 'campaign'
}

// ==================== AUTH ====================

export interface UserLogin {
  username?: string;
  email?: string;
  password: string;
}

export interface UserRegisterWithInvite {
  invite_code: string;
  username: string;
  password: string;
  full_name?: string;
  email?: string;
  phone?: string;
  address?: string;
  monthly_amount?: number;
}

export interface UserResponse {
  id: number;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserResponse;
}

// ==================== MEMBERS ====================

export interface MemberCreate {
  user_id: number;
  member_code: string;
  monthly_amount?: number;
  address?: string;
}

export interface MemberUpdate {
  monthly_amount?: number;
  address?: string;
  status?: string;
}

export interface MemberResponse {
  id: number;
  user_id: number;
  full_name: string | null;
  member_code: string;
  monthly_amount: number;
  address: string | null;
  join_date: string;
  status: string;
  created_at: string;
  updated_at: string;
}

// ==================== INVITES ====================

export interface InviteCreate {
  email?: string;
  phone?: string;
  expiry_date?: string;
  expires_at?: string;
}

export interface InviteUpdate {
  email?: string;
  phone?: string;
  expiry_date?: string;
  expires_at?: string;
}

export interface InviteResponse {
  id: number;
  invite_code: string;
  email: string | null;
  phone: string | null;
  is_used: boolean;
  expiry_date: string;
  created_at: string;
}

export interface InviteValidate {
  invite_code: string;
  email_or_phone: string;
}

// ==================== CAMPAIGNS ====================

export interface CampaignCreate {
  title: string;
  description?: string;
  target_amount: number;
  start_date: string;
  end_date: string;
}

export interface CampaignUpdate {
  title?: string;
  description?: string;
  target_amount?: number;
  start_date?: string;
  end_date?: string;
  is_active?: boolean;
}

export interface CampaignResponse {
  id: number;
  title: string;
  description: string | null;
  target_amount: number;
  start_date: string;
  end_date: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ==================== CHALLANS ====================

export interface ChallanCreate {
  member_id?: number;
  type: ChallanType;
  month?: string;
  campaign_id?: number;
  amount: number;
  payment_method?: string;
}

export interface ChallanApprove {
  approved_by_admin_id: number;
}

export interface ChallanReject {
  rejection_reason: string;
}

export interface ChallanResponse {
  id: number;
  member_id: number;
  type: ChallanType;
  month: string | null;
  campaign_id: number | null;
  amount: number;
  payment_method: string | null;
  proof_path: string | null;
  status: ChallanStatus;
  created_at: string;
  proof_uploaded_at: string | null;
  approved_at: string | null;
  updated_at: string;
}

// ==================== NOTIFICATIONS ====================

export interface NotificationCreate {
  user_id?: number;
  title: string;
  message: string;
  target_role?: UserRole;
}

export interface NotificationUpdate {
  is_read: boolean;
}

export interface NotificationAdminUpdate {
  title?: string;
  message?: string;
  is_read?: boolean;
}

export interface NotificationResponse {
  id: number;
  user_id: number;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
}

// ==================== AUDIT LOGS ====================

export interface AuditLogCreate {
  user_id?: number;
  action: string;
  entity_type: string;
  entity_id: number;
  old_values?: string;
  new_values?: string;
  ip_address?: string;
}

export interface AuditLogResponse {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: number;
  old_values: string | null;
  new_values: string | null;
  ip_address: string | null;
  created_at: string;
}

// ==================== FILES ====================

export interface FileUploadResponse {
  file_url: string;
  filename: string;
}

// ==================== ERRORS ====================

export interface ErrorDetail {
  type: string;
  loc: string[];
  msg: string;
  input: any;
}

export interface ErrorResponse {
  detail: ErrorDetail[];
}

// ==================== API RESPONSES ====================

export interface ApiResponse<T> {
  data?: T;
  error?: ErrorResponse;
  status: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total?: number;
  skip: number;
  limit: number;
}

// ==================== UTILITY TYPES ====================

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestConfig {
  method: HttpMethod;
  headers?: Record<string, string>;
  body?: any;
  params?: Record<string, any>;
}
```

---

## JSON Schema Validation (for form validation)

### Login Form Schema
```json
{
  "type": "object",
  "properties": {
    "email": {
      "type": "string",
      "format": "email"
    },
    "password": {
      "type": "string",
      "minLength": 8
    }
  },
  "required": ["password"],
  "oneOf": [
    { "required": ["email"] },
    { "required": ["username"] }
  ]
}
```

### Register Form Schema
```json
{
  "type": "object",
  "properties": {
    "invite_code": {
      "type": "string",
      "pattern": "^INV-[A-Z0-9]{6}$"
    },
    "username": {
      "type": "string",
      "minLength": 3,
      "maxLength": 50
    },
    "password": {
      "type": "string",
      "minLength": 8
    },
    "email": {
      "type": "string",
      "format": "email"
    },
    "phone": {
      "type": "string",
      "pattern": "^\\+?[1-9]\\d{1,14}$"
    },
    "monthly_amount": {
      "type": "number",
      "minimum": 0
    }
  },
  "required": ["invite_code", "username", "password"]
}
```

### Campaign Form Schema
```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "minLength": 3,
      "maxLength": 255
    },
    "description": {
      "type": "string"
    },
    "target_amount": {
      "type": "number",
      "minimum": 0,
      "exclusiveMinimum": true
    },
    "start_date": {
      "type": "string",
      "format": "date-time"
    },
    "end_date": {
      "type": "string",
      "format": "date-time"
    }
  },
  "required": ["title", "target_amount", "start_date", "end_date"]
}
```

---

## React Hook Form + Zod Example

```typescript
import { z } from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

// Login form schema
const loginSchema = z.object({
  email: z.string().email('Invalid email address').optional(),
  username: z.string().min(3).optional(),
  password: z.string().min(8, 'Password must be at least 8 characters'),
}).refine(data => data.email || data.username, {
  message: 'Either email or username is required',
  path: ['email'],
});

type LoginFormData = z.infer<typeof loginSchema>;

// Usage in component
const LoginForm = () => {
  const { register, handleSubmit, formState: { errors } } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormData) => {
    // Call API
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <input {...register('email')} placeholder="Email" />
      {errors.email && <span>{errors.email.message}</span>}
      
      <input {...register('password')} type="password" placeholder="Password" />
      {errors.password && <span>{errors.password.message}</span>}
      
      <button type="submit">Login</button>
    </form>
  );
};

// Campaign form schema
const campaignSchema = z.object({
  title: z.string().min(3).max(255),
  description: z.string().optional(),
  target_amount: z.number().positive(),
  start_date: z.string().datetime(),
  end_date: z.string().datetime(),
}).refine(data => new Date(data.end_date) > new Date(data.start_date), {
  message: 'End date must be after start date',
  path: ['end_date'],
});

type CampaignFormData = z.infer<typeof campaignSchema>;
```

---

## API Client Example

```typescript
// api-client.ts
import axios, { AxiosInstance, AxiosResponse } from 'axios';
import { 
  UserLogin, 
  TokenResponse, 
  CampaignResponse,
  ErrorResponse 
} from './types';

class ApiClient {
  private client: AxiosInstance;

  constructor(baseURL: string = 'http://localhost:8000') {
    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add token to requests
    this.client.interceptors.request.use(config => {
      const token = localStorage.getItem('access_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    // Handle errors
    this.client.interceptors.response.use(
      response => response,
      error => {
        if (error.response?.status === 401) {
          // Token expired, redirect to login
          localStorage.removeItem('access_token');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  async login(credentials: UserLogin): Promise<TokenResponse> {
    const response = await this.client.post<TokenResponse>('/auth/login', credentials);
    localStorage.setItem('access_token', response.data.access_token);
    return response.data;
  }

  async getCampaigns(activeOnly: boolean = false): Promise<CampaignResponse[]> {
    const response = await this.client.get<CampaignResponse[]>('/campaigns/', {
      params: { active_only: activeOnly },
    });
    return response.data;
  }

  async uploadFile(file: File): Promise<{ file_url: string; filename: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await this.client.post('/files/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    return response.data;
  }
}

export const apiClient = new ApiClient();
```

---

**End of JSON Schemas & TypeScript Interfaces**
