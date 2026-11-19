"""Imports every module that defines tables, so Base.metadata is complete for migrations."""

import app.agreements
import app.audit
import app.audit_stamps
import app.auth.mfa
import app.auth.sessions
import app.customer_services
import app.customers
import app.images
import app.jobs
import app.planning
import app.policy
import app.roles
import app.services
import app.users
import app.worklog  # noqa: F401
