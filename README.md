# Covid Prediction Clinic + MCP role-based assistant

## Run
```
pip install -r requirements.txt
cp .env.example .env            # set GROQ_API_KEY, SESSION_SECRET, MCP_SECRET
python -m src.pipeline.train_pipeline
uvicorn main:app --reload
pytest tests -q
```

## MCP servers (src/mcp_servers)
12 servers, each started as a separate stdio process (`python -m src.mcp_servers.servers.<name>`).

| Group | Servers | Who can call |
|---|---|---|
| Super user | `su_users`, `su_appointments`, `su_followups`, `su_audit` | `super_user` only. Any user's data + access audit log |
| User | `user_profile`, `user_appointments`, `user_followups`, `user_doctors` | `patient`, `super_user`. **Own data only** (tools have no `user_id` argument) |
| System | `system_booking_map`, `system_stats` | `system`, `super_user`. Which patient booked which doctor, aggregate stats |
| LLM security | `llm_input_guard`, `llm_output_guard` | Run by the agent on every message. Injection, privilege escalation, PII redaction, token budget; hallucinated doctors/fees, diagnosis/dosage, secret leaks |

**How access is decided:** the web app issues a short-lived signed token `{uid, role}` and starts only the servers the role may use, passing the token via `MCP_AUTH_TOKEN`. Each server verifies signature + expiry, re-reads the role from the DB, and checks it against the tool's allowed roles. Every call (allowed or denied) is written to `mcp_audit`.

**LLM connection:** `POST /api/assistant {"message": "..."}` -> `llm_agent.run_assistant` (input guard -> Groq tool-calling over the role's MCP servers -> output guard).

## Super user + "User activity" button
Put only a password in `.env` (no email). Signing up (or logging in) with **any email** and exactly this password gives the `super_user` role:
```
SUPERUSER_PASSWORD=a-strong-password-8+chars
```
Everyone sees a **"User activity"** button in the top nav. Click it to open a popup listing every user's name, role (Super user / Patient), login time and logout time (endpoint `/api/admin/users`, loaded through the `su_users` MCP server). Only super users get the data; patients get a 403 and logged-out visitors are asked to log in.

## Admin
```
python -m src.mcp_servers.cli set-role you@example.com super_user    # everyone signs up as patient
python -m src.mcp_servers.cli token --role system                    # service token for the system role
```
