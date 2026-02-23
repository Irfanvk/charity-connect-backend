# Change Report

**Scope:** From 2026-02-24 forward  
**Owner:** Release Manager

---

## 2026-02-24

### Backend
- [Added] POST /files/upload endpoint (3MB, jpg/png/pdf).
- [Changed] Login accepts email or username.
- [Changed] Auth service login flow queries by username or email.

### Frontend
- [Changed] Integration flow aligned to resource-specific routes (per frontend status).
- [Changed] Proof upload uses /files/upload (per frontend status).

### Docs
- [Added] COMMUNICATION_LOG.md template populated.
- [Changed] INTEGRATION_TESTING_GUIDE.md populated for Phase 1 testing.
- [Changed] CHANGE_REPORT.md populated and scoped.
- [Removed] Redundant integration docs moved to archive/.

### Notes
- Risks: Integration testing results pending.
- Follow-ups: Schedule joint testing session and record findings.
- Added frontend status report and backend confirmation checklist to integration guide.
