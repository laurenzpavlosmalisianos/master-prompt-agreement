Annex C — Scope of Authority (AUTHORITY.md)

_In consultancy framework agreements, this annex would define the contractor's authority limits, site access rules, and confidentiality obligations. Here it defines what the Contractor may and may not do in each environment._

Approval-Required Commands

[Commands the Contractor must never run without explicit per-invocation approval. Examples:]

- Database migrations in production
- Deploy commands (any environment)
- Destructive package operations (purge, uninstall --all)
- Infrastructure changes (Terraform apply, CloudFormation deploy)
- Service restarts or process kills

Environment Access

[Access levels by environment. Examples:]

- Development: autonomous operation. Read, write, execute without approval.
- Staging: write with approval. Read and test autonomously, deploy only with Client approval.
- Production: no direct access. All changes go through CI/CD pipeline.

Data Sensitivity

[Data classification and handling rules. Examples:]

- User PII: never log, display, or commit. Mask in test output.
- API keys and secrets: environment variables only. Never hardcode or commit.
- Test data: use obviously fake values. Never copy production data.
- Logs: strip sensitive fields before display. Do not include request bodies containing credentials.

Notes

- This annex is optional. If omitted, MSA Article 11 defaults apply.
- When this annex conflicts with MSA Article 11, the stricter rule applies.
