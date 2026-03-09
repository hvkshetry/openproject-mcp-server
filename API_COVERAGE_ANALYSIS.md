# API Coverage Analysis: OpenProject MCP vs OpenProject API v3 (v15.5.1)

Baseline used for this analysis:
- Server code reviewed: `openproject-mcp.py` (3,178 lines, 41 registered tools).
- OpenProject API source of truth: `opf/openproject` tag `v15.5.1` (`docs/api/apiv3/openapi-spec.yml` + `paths/*.yml`).
- Additional verification: DeepWiki (`opf/openproject`) and `gh api` inspection for module-mounted endpoints.

Coverage summary:
- API v3 operations in `docs/api/apiv3` at `v15.5.1`: **220**.
- Operations currently exposed via MCP tools in this server: **~37**.
- Operations not exposed as MCP tools: **183**.

Notable architecture observations from `openproject-mcp.py`:
- Single monolithic client+server file.
- Tool registration is static (`Tool(...)` repeated 41 times).
- Dispatch is a large `if/elif` in `call_tool`.
- No operation registry abstraction (resource + operation), so adding coverage grows branching and schema duplication.

## SECTION A — GAP ANALYSIS

| Resource | Endpoint | Method | Description | Priority (high/med/low) | PM Value |
|---|---|---|---|---|---|
| Activities/Journals | `/api/v3/activities/{id}` | `GET` | View activity | high | Comments/history are core PM communication |
| Activities/Journals | `/api/v3/activities/{id}` | `PATCH` | Update activity | high | Comments/history are core PM communication |
| Activities/Journals | `/api/v3/work_packages/{id}/activities` | `GET` | List work package activities | high | Comments/history are core PM communication |
| Activities/Journals | `/api/v3/work_packages/{id}/activities` | `POST` | Comment work package | high | Comments/history are core PM communication |
| Attachments | `/api/v3/attachments` | `POST` | Create Attachment | high | Task-level file workflows and evidence |
| Attachments | `/api/v3/attachments/{id}` | `DELETE` | Delete attachment | high | Task-level file workflows and evidence |
| Attachments | `/api/v3/attachments/{id}` | `GET` | View attachment | high | Task-level file workflows and evidence |
| Attachments | `/api/v3/work_packages/{id}/attachments` | `GET` | List attachments by work package | high | Task-level file workflows and evidence |
| Attachments | `/api/v3/work_packages/{id}/attachments` | `POST` | Create work package attachment | high | Task-level file workflows and evidence |
| File Links | `/api/v3/file_links/{id}` | `DELETE` | Removes a file link. | high | External file collaboration from work packages |
| File Links | `/api/v3/file_links/{id}` | `GET` | Gets a file link. | high | External file collaboration from work packages |
| File Links | `/api/v3/file_links/{id}/download` | `GET` | Creates a download uri of the linked file. | high | External file collaboration from work packages |
| File Links | `/api/v3/file_links/{id}/open` | `GET` | Creates an opening uri of the linked file. | high | External file collaboration from work packages |
| File Links | `/api/v3/work_packages/{id}/file_links` | `GET` | Gets all file links of a work package | high | External file collaboration from work packages |
| File Links | `/api/v3/work_packages/{id}/file_links` | `POST` | Creates file links. | high | External file collaboration from work packages |
| Notifications | `/api/v3/notifications` | `GET` | Get notification collection | high | Inbox triage and read/unread automation |
| Notifications | `/api/v3/notifications/read_ian` | `POST` | Read all notifications | high | Inbox triage and read/unread automation |
| Notifications | `/api/v3/notifications/unread_ian` | `POST` | Unread all notifications | high | Inbox triage and read/unread automation |
| Notifications | `/api/v3/notifications/{id}` | `GET` | Get the notification | high | Inbox triage and read/unread automation |
| Notifications | `/api/v3/notifications/{id}/read_ian` | `POST` | Read notification | high | Inbox triage and read/unread automation |
| Notifications | `/api/v3/notifications/{id}/unread_ian` | `POST` | Unread notification | high | Inbox triage and read/unread automation |
| Notifications | `/api/v3/notifications/{notification_id}/details/{id}` | `GET` | Get a notification detail | high | Inbox triage and read/unread automation |
| Queries | `/api/v3/projects/{id}/queries/default` | `GET` | View default query for project | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/projects/{id}/queries/filter_instance_schemas` | `GET` | List Query Filter Instance Schemas for Project | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/projects/{id}/queries/schema` | `GET` | View schema for project queries | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries` | `GET` | List queries | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries` | `POST` | Create query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/available_projects` | `GET` | Available projects for query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/columns/{id}` | `GET` | View Query Column | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/default` | `GET` | View default query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/filter_instance_schemas` | `GET` | List Query Filter Instance Schemas | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/filter_instance_schemas/{id}` | `GET` | View Query Filter Instance Schema | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/filters/{id}` | `GET` | View Query Filter | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/form` | `POST` | Query Create Form | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/operators/{id}` | `GET` | View Query Operator | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/schema` | `GET` | View schema for global queries | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/sort_bys/{id}` | `GET` | View Query Sort By | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/{id}` | `DELETE` | Delete query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/{id}` | `GET` | View query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/{id}` | `PATCH` | Edit Query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/{id}/form` | `POST` | Query Update Form | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/{id}/star` | `PATCH` | Star query | high | Saved filters/default views drive PM workflows |
| Queries | `/api/v3/queries/{id}/unstar` | `PATCH` | Unstar query | high | Saved filters/default views drive PM workflows |
| Versions | `/api/v3/versions/available_projects` | `GET` | Available projects for versions | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/form` | `POST` | Version create form | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/schema` | `GET` | View version schema | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/{id}` | `DELETE` | Delete version | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/{id}` | `GET` | View version | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/{id}` | `PATCH` | Update Version | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/{id}/form` | `POST` | Version update form | high | Milestone lifecycle is incomplete without update/delete |
| Versions | `/api/v3/versions/{id}/projects` | `GET` | List projects having version | high | Milestone lifecycle is incomplete without update/delete |
| Views | `/api/v3/views` | `GET` | List views | high | Board/table/timeline view state management |
| Views | `/api/v3/views/{id}` | `GET` | View view | high | Board/table/timeline view state management |
| Views | `/api/v3/views/{id}` | `POST` | Create view | high | Board/table/timeline view state management |
| Work Package Schemas/Forms | `/api/v3/projects/{id}/work_packages/form` | `POST` | Form for creating Work Packages in a Project | high | Dynamic validation and allowed values for safe create/update |
| Work Package Schemas/Forms | `/api/v3/work_packages/form` | `POST` | Form for creating a Work Package | high | Dynamic validation and allowed values for safe create/update |
| Work Package Schemas/Forms | `/api/v3/work_packages/schemas` | `GET` | List Work Package Schemas | high | Dynamic validation and allowed values for safe create/update |
| Work Package Schemas/Forms | `/api/v3/work_packages/schemas/{identifier}` | `GET` | View Work Package Schema | high | Dynamic validation and allowed values for safe create/update |
| Work Package Schemas/Forms | `/api/v3/work_packages/{id}/form` | `POST` | Form for editing a Work Package | high | Dynamic validation and allowed values for safe create/update |
| Availability Helpers | `/api/v3/projects/{id}/available_assignees` | `GET` | Project Available assignees | med | Resolve valid assignees/projects/relations/watchers |
| Availability Helpers | `/api/v3/work_packages/{id}/available_assignees` | `GET` | Work Package Available assignees | med | Resolve valid assignees/projects/relations/watchers |
| Availability Helpers | `/api/v3/work_packages/{id}/available_projects` | `GET` | Available projects for work package | med | Resolve valid assignees/projects/relations/watchers |
| Availability Helpers | `/api/v3/work_packages/{id}/available_relation_candidates` | `GET` | Available relation candidates | med | Resolve valid assignees/projects/relations/watchers |
| Availability Helpers | `/api/v3/work_packages/{id}/available_watchers` | `GET` | Available watchers | med | Resolve valid assignees/projects/relations/watchers |
| Budgets | `/api/v3/budgets/{id}` | `GET` | view Budget | med | Budget visibility for delivery planning |
| Budgets | `/api/v3/projects/{id}/budgets` | `GET` | view Budgets of a Project | med | Budget visibility for delivery planning |
| Categories | `/api/v3/categories/{id}` | `GET` | View Category | med | Project taxonomy used in planning/reporting |
| Categories | `/api/v3/projects/{id}/categories` | `GET` | List categories of a project | med | Project taxonomy used in planning/reporting |
| Custom Actions | `/api/v3/custom_actions/{id}` | `GET` | Get a custom action | med | Execute server-side workflow automations |
| Custom Actions | `/api/v3/custom_actions/{id}/execute` | `POST` | Execute custom action | med | Execute server-side workflow automations |
| Custom Fields | `/api/v3/custom_field_items/{id}` | `GET` | Get a custom field hierarchy item | med | Resolve dynamic custom field values/hierarchies |
| Custom Fields | `/api/v3/custom_field_items/{id}/branch` | `GET` | Get a custom field hierarchy item's branch | med | Resolve dynamic custom field values/hierarchies |
| Custom Fields | `/api/v3/custom_fields/{id}/items` | `GET` | Get the custom field hierarchy items | med | Resolve dynamic custom field values/hierarchies |
| Custom Fields | `/api/v3/custom_options/{id}` | `GET` | View Custom Option | med | Resolve dynamic custom field values/hierarchies |
| Custom Fields | `/api/v3/values/schema/{id}` | `GET` | View Values schema | med | Resolve dynamic custom field values/hierarchies |
| Grids/Boards | `/api/v3/grids` | `GET` | List grids | med | Manage board/grid entities |
| Grids/Boards | `/api/v3/grids` | `POST` | Create a grid | med | Manage board/grid entities |
| Grids/Boards | `/api/v3/grids/form` | `POST` | Grid Create Form | med | Manage board/grid entities |
| Grids/Boards | `/api/v3/grids/{id}` | `GET` | Get a grid | med | Manage board/grid entities |
| Grids/Boards | `/api/v3/grids/{id}` | `PATCH` | Update a grid | med | Manage board/grid entities |
| Grids/Boards | `/api/v3/grids/{id}/form` | `POST` | Grid Update Form | med | Manage board/grid entities |
| Groups | `/api/v3/groups` | `GET` | List groups | med | Group-based assignment and access |
| Groups | `/api/v3/groups` | `POST` | Create group | med | Group-based assignment and access |
| Groups | `/api/v3/groups/{id}` | `DELETE` | Delete group | med | Group-based assignment and access |
| Groups | `/api/v3/groups/{id}` | `GET` | Get group | med | Group-based assignment and access |
| Groups | `/api/v3/groups/{id}` | `PATCH` | Update group | med | Group-based assignment and access |
| Membership Forms | `/api/v3/memberships/available_projects` | `GET` | Available projects for memberships | med | Validation helpers for role assignments |
| Membership Forms | `/api/v3/memberships/form` | `POST` | Form create membership | med | Validation helpers for role assignments |
| Membership Forms | `/api/v3/memberships/schema` | `GET` | Schema membership | med | Validation helpers for role assignments |
| Membership Forms | `/api/v3/memberships/{id}/form` | `POST` | Form update membership | med | Validation helpers for role assignments |
| News | `/api/v3/news` | `GET` | List News | med | Project communications and announcements |
| News | `/api/v3/news` | `POST` | Create News | med | Project communications and announcements |
| News | `/api/v3/news/{id}` | `DELETE` | Delete news | med | Project communications and announcements |
| News | `/api/v3/news/{id}` | `GET` | View news | med | Project communications and announcements |
| News | `/api/v3/news/{id}` | `PATCH` | Update news | med | Project communications and announcements |
| Placeholder Users | `/api/v3/placeholder_users` | `GET` | List placehoder users | med | Planning with non-person placeholders |
| Placeholder Users | `/api/v3/placeholder_users` | `POST` | Create placeholder user | med | Planning with non-person placeholders |
| Placeholder Users | `/api/v3/placeholder_users/{id}` | `DELETE` | Delete placeholder user | med | Planning with non-person placeholders |
| Placeholder Users | `/api/v3/placeholder_users/{id}` | `GET` | View placeholder user | med | Planning with non-person placeholders |
| Placeholder Users | `/api/v3/placeholder_users/{id}` | `PATCH` | Update placeholder user | med | Planning with non-person placeholders |
| Projects | `/api/v3/projects/available_parent_projects` | `GET` | List available parent project candidates | med | Project setup/copy/template workflows |
| Projects | `/api/v3/projects/form` | `POST` | Project create form | med | Project setup/copy/template workflows |
| Projects | `/api/v3/projects/schema` | `GET` | View project schema | med | Project setup/copy/template workflows |
| Projects | `/api/v3/projects/{id}/copy` | `POST` | Create project copy | med | Project setup/copy/template workflows |
| Projects | `/api/v3/projects/{id}/copy/form` | `POST` | Project copy form | med | Project setup/copy/template workflows |
| Projects | `/api/v3/projects/{id}/form` | `POST` | Project update form | med | Project setup/copy/template workflows |
| Revisions/Reminders | `/api/v3/revisions/{id}` | `GET` | View revision | med | Audit trail and reminder awareness |
| Revisions/Reminders | `/api/v3/work_packages/{id}/reminders` | `GET` | Reminders | med | Audit trail and reminder awareness |
| Revisions/Reminders | `/api/v3/work_packages/{id}/revisions` | `GET` | Revisions | med | Audit trail and reminder awareness |
| Storages | `/api/v3/project_storages` | `GET` | Gets a list of project storages | med | External document storage integration |
| Storages | `/api/v3/project_storages/{id}` | `GET` | Gets a project storage | med | External document storage integration |
| Storages | `/api/v3/project_storages/{id}/open` | `GET` | Open the project storage | med | External document storage integration |
| Storages | `/api/v3/storages` | `GET` | Get Storages | med | External document storage integration |
| Storages | `/api/v3/storages` | `POST` | Creates a storage. | med | External document storage integration |
| Storages | `/api/v3/storages/{id}` | `DELETE` | Delete a storage | med | External document storage integration |
| Storages | `/api/v3/storages/{id}` | `GET` | Get a storage | med | External document storage integration |
| Storages | `/api/v3/storages/{id}` | `PATCH` | Update a storage | med | External document storage integration |
| Storages | `/api/v3/storages/{id}/files` | `GET` | Gets files of a storage. | med | External document storage integration |
| Storages | `/api/v3/storages/{id}/files/prepare_upload` | `POST` | Preparation of a direct upload of a file to the given storage. | med | External document storage integration |
| Storages | `/api/v3/storages/{id}/folders` | `POST` | Creation of a new folder | med | External document storage integration |
| Storages | `/api/v3/storages/{id}/oauth_client_credentials` | `POST` | Creates an oauth client credentials object for a storage. | med | External document storage integration |
| Storages | `/api/v3/storages/{id}/open` | `GET` | Open the storage | med | External document storage integration |
| Time Entries | `/api/v3/time_entries/activity/{id}` | `GET` | View time entries activity | med | Form/schema + single-entry operations |
| Time Entries | `/api/v3/time_entries/available_projects` | `GET` | Available projects for time entries | med | Form/schema + single-entry operations |
| Time Entries | `/api/v3/time_entries/form` | `POST` | Time entry create form | med | Form/schema + single-entry operations |
| Time Entries | `/api/v3/time_entries/schema` | `GET` | View time entry schema | med | Form/schema + single-entry operations |
| Time Entries | `/api/v3/time_entries/{id}` | `GET` | Get time entry | med | Form/schema + single-entry operations |
| Time Entries | `/api/v3/time_entries/{id}/form` | `POST` | Time entry update form | med | Form/schema + single-entry operations |
| Users | `/api/v3/users` | `POST` | Create User | med | User lifecycle and account state automation |
| Users | `/api/v3/users/schema` | `GET` | View user schema | med | User lifecycle and account state automation |
| Users | `/api/v3/users/{id}` | `DELETE` | Delete user | med | User lifecycle and account state automation |
| Users | `/api/v3/users/{id}` | `PATCH` | Update user | med | User lifecycle and account state automation |
| Users | `/api/v3/users/{id}/form` | `POST` | User update form | med | User lifecycle and account state automation |
| Users | `/api/v3/users/{id}/lock` | `DELETE` | Unlock user | med | User lifecycle and account state automation |
| Users | `/api/v3/users/{id}/lock` | `POST` | Lock user | med | User lifecycle and account state automation |
| Wiki Pages | `/api/v3/wiki_pages/{id}` | `GET` | View Wiki Page | med | Project documentation and attachments |
| Wiki Pages | `/api/v3/wiki_pages/{id}/attachments` | `GET` | List attachments by wiki page | med | Project documentation and attachments |
| Wiki Pages | `/api/v3/wiki_pages/{id}/attachments` | `POST` | Add attachment to wiki page | med | Project documentation and attachments |
| Work Package Watchers | `/api/v3/work_packages/{id}/watchers` | `GET` | List watchers | med | Stakeholder subscription management |
| Work Package Watchers | `/api/v3/work_packages/{id}/watchers` | `POST` | Add watcher | med | Stakeholder subscription management |
| Work Package Watchers | `/api/v3/work_packages/{id}/watchers/{user_id}` | `DELETE` | Remove watcher | med | Stakeholder subscription management |
| Documents/Posts/Meetings | `/api/v3/documents` | `GET` | List Documents | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/documents/{id}` | `GET` | View document | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/meetings/{id}` | `GET` | View Meeting Page | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/meetings/{id}/attachments` | `GET` | List attachments by meeting | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/meetings/{id}/attachments` | `POST` | Add attachment to meeting | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/posts/{id}` | `GET` | View Post | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/posts/{id}/attachments` | `GET` | List attachments by post | low | Supplementary collaboration content |
| Documents/Posts/Meetings | `/api/v3/posts/{id}/attachments` | `POST` | Add attachment to post | low | Supplementary collaboration content |
| Lookup Details | `/api/v3/priorities/{id}` | `GET` | View Priority | low | Single-item lookup; list endpoints already exist |
| Lookup Details | `/api/v3/statuses/{id}` | `GET` | Get a work package status | low | Single-item lookup; list endpoints already exist |
| Lookup Details | `/api/v3/types/{id}` | `GET` | View Type | low | Single-item lookup; list endpoints already exist |
| Other | `/api/v3/projects/{id}/work_packages` | `POST` | Create work package in project | low | Niche endpoint |
| Platform/Admin | `/api/v3/actions` | `GET` | List actions | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/actions/{id}` | `GET` | View action | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/capabilities` | `GET` | List capabilities | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/capabilities/context/global` | `GET` | View global context | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/capabilities/{id}` | `GET` | View capabilities | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/configuration` | `GET` | View configuration | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days` | `GET` | Lists days | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/non_working` | `GET` | Lists all non working days | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/non_working` | `POST` | Creates a non-working day (NOT IMPLEMENTED) | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/non_working/{date}` | `DELETE` | Removes a non-working day (NOT IMPLEMENTED) | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/non_working/{date}` | `GET` | View a non-working day | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/non_working/{date}` | `PATCH` | Update a non-working day attributes (NOT IMPLEMENTED) | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/week` | `GET` | Lists week days | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/week` | `PATCH` | Update week days (NOT IMPLEMENTED) | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/week/{day}` | `GET` | View a week day | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/week/{day}` | `PATCH` | Update a week day attributes (NOT IMPLEMENTED) | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/days/{date}` | `GET` | View day | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/example/form` | `POST` | show or validate form | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/example/schema` | `GET` | view the schema | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/examples` | `GET` | view aggregated result | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/help_texts` | `GET` | List help texts | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/help_texts/{id}` | `GET` | Get help text | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/my_preferences` | `GET` | Show my preferences | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/my_preferences` | `PATCH` | Update my preferences | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/oauth_applications/{id}` | `GET` | Get the oauth application. | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/oauth_client_credentials/{id}` | `GET` | Get the oauth client credentials object. | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/principals` | `GET` | List principals | low | Platform metadata/admin utility endpoints |
| Platform/Admin | `/api/v3/project_statuses/{id}` | `GET` | View project status | low | Platform metadata/admin utility endpoints |
| Rendering | `/api/v3/render/markdown` | `POST` | Preview Markdown document | low | Server-side markdown/plain rendering |
| Rendering | `/api/v3/render/plain` | `POST` | Preview plain document | low | Server-side markdown/plain rendering |

### Module-Mounted API Operations Not Present In `docs/api/apiv3/openapi-spec.yml`

These are mounted in repository code (`modules/costs/lib/costs/engine.rb`) and are relevant for cost-tracking installations.

| Resource | Endpoint | Method | Description | Priority (high/med/low) | PM Value |
|---|---|---|---|---|---|
| Cost Entries (module) | `/api/v3/cost_entries/{id}` | `GET` | View a single cost entry (mounted via `CostEntriesAPI`). | med | Cost transparency for budget-sensitive plans |
| Cost Entries (module) | `/api/v3/work_packages/{id}/cost_entries` | `GET` | List cost entries for a work package (mounted via `CostEntriesByWorkPackageAPI`). | med | Full work item actuals (time + material costs) |
| Cost Summary (module) | `/api/v3/work_packages/{id}/summarized_costs_by_type` | `GET` | View summarized costs by type for a work package. | med | Fast budget rollups in PM workflows |
| Cost Types (module) | `/api/v3/cost_types/{id}` | `GET` | View cost type definition. | low | Reference lookup for cost interpretation |

### Important Version Notes

- Query model fields are partially deprecated in v15.5.1 docs; display-oriented properties are being moved toward `Views`.
- `/api/v3/queries/*` and `/api/v3/views/*` both matter for modern PM UX.
- Several `days/*` operations are explicitly marked as "NOT IMPLEMENTED" in API docs; these are low priority for PM agents.
- The server currently calls `/api/v3/time_entries/activities`, while v15.5.1 OpenAPI documents `/api/v3/time_entries/activity/{id}`.

## SECTION B — CONSOLIDATION PROPOSAL

Target: replace 41 atomic tools with a smaller operation-enum surface that is easier for LLM planning while increasing API coverage.

### Proposed Tool Model

All tools follow one pattern:

```json
{
  "operation": "<enum>",
  "ids": {},
  "filters": {},
  "payload": {},
  "options": {}
}
```

- `operation`: required enum that selects behavior.
- `ids`: typed identifiers relevant to the selected operation.
- `filters`: list/query filter object(s) used by list operations.
- `payload`: create/update/form payload.
- `options`: pagination, include flags, feature flags (e.g., `use_form_validation`).

### Proposed Consolidated Tool Set (10 tools)

1. `project`
- operation enum:
  `list|get|create|update|delete|schema|form_create|form_update|copy|copy_form|list_available_parent_projects|list_work_packages|create_work_package|work_packages_form|list_types|list_versions|list_categories|list_budgets|list_available_assignees`
- params:
  `project_id?`, `source_project_id?`, `filters?`, `sort_by?`, `select?`, `offset?`, `page_size?`, `payload?`

2. `work_package`
- operation enum:
  `list|get|create|update|delete|schema_list|schema_get|form_create|form_update|set_parent|remove_parent|list_children|list_activities|add_comment|list_attachments|add_attachment|list_available_assignees|list_available_projects|list_available_relation_candidates|list_available_watchers|list_watchers|add_watcher|remove_watcher|list_file_links|create_file_link|get_file_link|open_file_link|download_file_link|delete_file_link|list_revisions|list_reminders|list_relations|create_relation|get_relation|update_relation|delete_relation`
- params:
  `work_package_id?`, `relation_id?`, `parent_id?`, `user_id?`, `include_descendants?`, `relation_type?`, `from_id?`, `to_id?`, `lag?`, `filters?`, `payload?`

3. `time_entry`
- operation enum:
  `list|get|create|update|delete|get_activity|list_available_projects|schema|form_create|form_update`
- params:
  `time_entry_id?`, `activity_id?`, `project_id?`, `work_package_id?`, `user_id?`, `filters?`, `payload?`

4. `membership`
- operation enum:
  `list|get|create|update|delete|schema|form_create|form_update|list_available_projects|list_project_members|list_user_projects`
- params:
  `membership_id?`, `project_id?`, `user_id?`, `group_id?`, `role_ids?`, `filters?`, `payload?`

5. `principal`
- operation enum:
  `list_users|get_user|create_user|update_user|delete_user|user_schema|user_form|lock_user|unlock_user|list_groups|get_group|create_group|update_group|delete_group|list_placeholder_users|get_placeholder_user|create_placeholder_user|update_placeholder_user|delete_placeholder_user|list_roles|get_role|list_principals`
- params:
  `user_id?`, `group_id?`, `placeholder_user_id?`, `role_id?`, `filters?`, `payload?`

6. `version`
- operation enum:
  `list|get|create|update|delete|schema|form_create|form_update|list_available_projects|list_projects`
- params:
  `version_id?`, `project_id?`, `filters?`, `payload?`

7. `query_view`
- operation enum:
  `list_queries|get_query|create_query|update_query|delete_query|query_schema|query_form_create|query_form_update|get_default_query|get_project_default_query|list_available_projects|list_filter_instance_schemas|get_filter_instance_schema|get_filter|get_column|get_operator|get_sort_by|star_query|unstar_query|list_views|get_view|create_view`
- params:
  `query_id?`, `view_id_or_type?`, `project_id?`, `filter_id?`, `operator_id?`, `column_id?`, `sort_by_id?`, `filters?`, `payload?`

8. `notification`
- operation enum:
  `list|get|get_detail|mark_read|mark_unread|mark_all_read|mark_all_unread`
- params:
  `notification_id?`, `detail_id?`, `filters?`

9. `artifact`
- operation enum:
  `list_news|get_news|create_news|update_news|delete_news|get_wiki_page|list_wiki_attachments|add_wiki_attachment|list_documents|get_document|get_post|list_post_attachments|add_post_attachment|get_meeting|list_meeting_attachments|add_meeting_attachment|create_attachment|get_attachment|delete_attachment`
- params:
  `news_id?`, `wiki_page_id?`, `document_id?`, `post_id?`, `meeting_id?`, `attachment_id?`, `filters?`, `payload?`

10. `integration`
- operation enum:
  `list_storages|get_storage|create_storage|update_storage|delete_storage|open_storage|list_storage_files|prepare_storage_upload|create_storage_folder|create_storage_oauth_client_credentials|list_project_storages|get_project_storage|open_project_storage|get_configuration|list_capabilities|get_capability|get_global_capabilities|list_actions|get_action|render_markdown|render_plain|get_preferences|update_preferences|list_statuses|get_status|list_priorities|get_priority|list_types|get_type|get_category|get_custom_action|execute_custom_action|get_custom_field_items|get_custom_field_item|get_custom_field_item_branch|get_custom_option|get_values_schema`
- params:
  `storage_id?`, `project_storage_id?`, `capability_id?`, `action_id?`, `status_id?`, `priority_id?`, `type_id?`, `category_id?`, `custom_action_id?`, `custom_field_id?`, `custom_field_item_id?`, `custom_option_id?`, `schema_id?`, `filters?`, `payload?`

### Count Comparison

- Current: **41 atomic tools**.
- Proposed: **10 parameterized tools**.
- Net reduction: **31 fewer tools** (~**75.6%** reduction) while expanding endpoint coverage.

### LLM Usability Tradeoffs

Benefits:
- Fewer tool names lowers tool-selection entropy for the model.
- Operation enums make intent explicit and easier to route.
- Shared parameter conventions reduce prompt tokens and repeated explanation.
- Easier to add future endpoints by extending enums instead of creating new tool names.

Risks:
- Larger enums can cause wrong operation selection.
- Invalid parameter combinations become more likely.
- Tool schemas can become hard to read if unconstrained.

Mitigations:
- Use `oneOf`/operation-specific schema branches so each `operation` has strict required/optional params.
- Return structured validation errors that include the expected fields for the selected operation.
- Keep compatibility aliases for existing 41 tool names during migration, then deprecate.
- Add a lightweight `discover_operations` helper that returns supported operations per tool at runtime.

### Implementation Fit For Current Server Architecture

Given the existing monolithic `list_tools` + `call_tool` structure, the most maintainable migration is:
- Introduce an operation registry map: `(tool_name, operation) -> handler`.
- Reuse existing client methods first, then add missing client methods by resource.
- Move text rendering to shared formatters so each operation returns predictable structured data plus concise human summary.
- Add endpoint compatibility tests that compare declared operations to OpenAPI path/method coverage for `v15.5.1`.
