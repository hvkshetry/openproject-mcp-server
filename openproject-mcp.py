#!/usr/bin/env python3
"""
OpenProject MCP Server — Consolidated Architecture (v2.1)

10 parameterized tools covering ~122 API operations via operation registry.
v2.1 adds: day/schedule, budgets, attachment upload, file links, baseline
timestamps, custom field introspection, schema/form validation, and views.

Tools: project, work_package, time_entry, membership, principal,
       version, query_view, notification, artifact, integration
"""

import os
import json
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import aiohttp
from urllib.parse import quote
import base64
import ssl
from dotenv import load_dotenv

from mcp.server import Server
from mcp.types import Tool, TextContent

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

__version__ = "2.1.1"


def _parse_iso_duration_hours(duration_str: str) -> str:
    """Parse ISO 8601 duration (PT2H30M) to decimal hours string."""
    if not duration_str or "PT" not in duration_str:
        return "0"
    match = re.match(
        r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?",
        duration_str,
    )
    if not match:
        return duration_str
    h = float(match.group(1) or 0)
    m = float(match.group(2) or 0)
    total = h + m / 60
    return str(int(total)) if total == int(total) else f"{total:.1f}"


# ═══════════════════════════════════════════════════════════════════════
# OpenProject API Client
# ═══════════════════════════════════════════════════════════════════════


class OpenProjectClient:
    """Client for the OpenProject API v3 with generic + complex helpers."""

    def __init__(self, base_url: str, api_key: str, proxy: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.proxy = proxy
        self.headers = {
            "Authorization": f"Basic {self._encode_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"OpenProject-MCP/{__version__}",
        }
        logger.info(f"OpenProject Client initialized for: {self.base_url}")
        if self.proxy:
            logger.info(f"Using proxy: {self.proxy}")

    def _encode_api_key(self) -> str:
        credentials = f"apikey:{self.api_key}"
        return base64.b64encode(credentials.encode()).decode()

    async def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None
    ) -> Dict:
        url = f"{self.base_url}/api/v3{endpoint}"
        logger.debug(f"API Request: {method} {url}")
        if data:
            logger.debug(f"Request body: {json.dumps(data, indent=2)}")

        ssl_context = ssl.create_default_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout
        ) as session:
            try:
                request_params = {
                    "method": method,
                    "url": url,
                    "headers": self.headers,
                    "json": data,
                }
                if self.proxy:
                    request_params["proxy"] = self.proxy

                async with session.request(**request_params) as response:
                    response_text = await response.text()
                    logger.debug(f"Response status: {response.status}")

                    try:
                        response_json = (
                            json.loads(response_text) if response_text else {}
                        )
                    except json.JSONDecodeError:
                        logger.error(
                            f"Invalid JSON response: {response_text[:200]}..."
                        )
                        response_json = {}

                    if response.status >= 400:
                        raise Exception(
                            self._format_error(response.status, response_text)
                        )

                    return response_json

            except aiohttp.ClientError as e:
                logger.error(f"Network error: {str(e)}")
                raise Exception(f"Network error accessing {url}: {str(e)}")

    def _format_error(self, status: int, response_text: str) -> str:
        hints = {
            401: "Authentication failed. Check API key.",
            403: "Access denied. User lacks permissions.",
            404: "Resource not found.",
            407: "Proxy authentication required.",
            422: "Validation error.",
            500: "Internal server error.",
            502: "Bad gateway.",
            503: "Service unavailable.",
        }
        msg = f"API Error {status}: {response_text}"
        if status in hints:
            msg += f"\n\n{hints[status]}"
        return msg

    # ── Generic helpers ──────────────────────────────────────────────

    async def get(self, endpoint: str) -> Dict:
        return await self._request("GET", endpoint)

    async def post(self, endpoint: str, data: Optional[Dict] = None) -> Dict:
        return await self._request("POST", endpoint, data)

    async def patch(self, endpoint: str, data: Optional[Dict] = None) -> Dict:
        return await self._request("PATCH", endpoint, data)

    async def delete_resource(self, endpoint: str) -> bool:
        await self._request("DELETE", endpoint)
        return True

    async def post_text(self, endpoint: str, text: str, content_type: str = "text/plain") -> Dict:
        """POST raw text body (e.g. for /render/markdown)."""
        url = f"{self.base_url}/api/v3{endpoint}"
        headers = {**self.headers, "Content-Type": content_type}
        ssl_context = ssl.create_default_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            request_params = {"method": "POST", "url": url, "headers": headers, "data": text.encode("utf-8")}
            if self.proxy:
                request_params["proxy"] = self.proxy
            async with session.request(**request_params) as response:
                response_text = await response.text()
                if response.status >= 400:
                    raise Exception(self._format_error(response.status, response_text))
                return {"html": response_text}

    def _ensure_collection(self, result: Dict) -> List[Dict]:
        """Extract elements list from a collection response."""
        if "_embedded" not in result:
            return []
        return result.get("_embedded", {}).get("elements", [])

    async def get_collection(self, endpoint: str) -> List[Dict]:
        """GET a collection endpoint and return elements list."""
        result = await self._request("GET", endpoint)
        return self._ensure_collection(result)

    # ── Complex operations (form/lock-version logic) ─────────────────

    async def create_work_package(self, data: Dict) -> Dict:
        form_payload = {"_links": {}}
        if "project" in data:
            form_payload["_links"]["project"] = {
                "href": f"/api/v3/projects/{data['project']}"
            }
        if "type" in data:
            form_payload["_links"]["type"] = {
                "href": f"/api/v3/types/{data['type']}"
            }
        if "subject" in data:
            form_payload["subject"] = data["subject"]

        form = await self._request("POST", "/work_packages/form", form_payload)
        payload = form.get("payload", form_payload)
        payload["lockVersion"] = form.get("lockVersion", 0)

        if "description" in data:
            payload["description"] = {"raw": data["description"]}
        if "priority_id" in data:
            payload.setdefault("_links", {})["priority"] = {
                "href": f"/api/v3/priorities/{data['priority_id']}"
            }
        if "assignee_id" in data:
            payload.setdefault("_links", {})["assignee"] = {
                "href": f"/api/v3/users/{data['assignee_id']}"
            }
        for f in ("startDate", "dueDate", "date"):
            if f in data:
                payload[f] = data[f]
        return await self._request("POST", "/work_packages", payload)

    async def update_work_package(self, wp_id: int, data: Dict) -> Dict:
        current = await self._request("GET", f"/work_packages/{wp_id}")
        payload = {"lockVersion": current.get("lockVersion", 0)}

        if "subject" in data:
            payload["subject"] = data["subject"]
        if "description" in data:
            payload["description"] = {"raw": data["description"]}

        link_map = {
            "type_id": ("type", "/api/v3/types/{}"),
            "status_id": ("status", "/api/v3/statuses/{}"),
            "priority_id": ("priority", "/api/v3/priorities/{}"),
            "assignee_id": ("assignee", "/api/v3/users/{}"),
        }
        for key, (link_name, href_tpl) in link_map.items():
            if key in data:
                payload.setdefault("_links", {})[link_name] = {
                    "href": href_tpl.format(data[key])
                }
        if "percentage_done" in data:
            payload["percentageDone"] = data["percentage_done"]
        for f in ("startDate", "dueDate", "date"):
            if f in data:
                payload[f] = data[f]
        return await self._request("PATCH", f"/work_packages/{wp_id}", payload)

    async def set_work_package_parent(self, wp_id: int, parent_id: int) -> Dict:
        current = await self._request("GET", f"/work_packages/{wp_id}")
        payload = {
            "lockVersion": current.get("lockVersion", 0),
            "_links": {"parent": {"href": f"/api/v3/work_packages/{parent_id}"}},
        }
        return await self._request("PATCH", f"/work_packages/{wp_id}", payload)

    async def remove_work_package_parent(self, wp_id: int) -> Dict:
        current = await self._request("GET", f"/work_packages/{wp_id}")
        payload = {
            "lockVersion": current.get("lockVersion", 0),
            "_links": {"parent": None},
        }
        return await self._request("PATCH", f"/work_packages/{wp_id}", payload)

    async def create_time_entry(self, data: Dict) -> Dict:
        payload = {}
        if "work_package_id" in data:
            payload["_links"] = {
                "workPackage": {
                    "href": f"/api/v3/work_packages/{data['work_package_id']}"
                }
            }
        if "hours" in data:
            payload["hours"] = f"PT{data['hours']}H"
        if "spent_on" in data:
            payload["spentOn"] = data["spent_on"]
        if "comment" in data:
            payload["comment"] = {"raw": data["comment"]}
        if "activity_id" in data:
            payload.setdefault("_links", {})["activity"] = {
                "href": f"/api/v3/time_entries/activities/{data['activity_id']}"
            }
        return await self._request("POST", "/time_entries", payload)

    async def update_time_entry(self, te_id: int, data: Dict) -> Dict:
        current = await self._request("GET", f"/time_entries/{te_id}")
        payload = {"lockVersion": current.get("lockVersion", 0)}
        if "hours" in data:
            payload["hours"] = f"PT{data['hours']}H"
        if "spent_on" in data:
            payload["spentOn"] = data["spent_on"]
        if "comment" in data:
            payload["comment"] = {"raw": data["comment"]}
        if "activity_id" in data:
            payload.setdefault("_links", {})["activity"] = {
                "href": f"/api/v3/time_entries/activities/{data['activity_id']}"
            }
        return await self._request("PATCH", f"/time_entries/{te_id}", payload)

    async def create_membership(self, data: Dict) -> Dict:
        payload = {"_links": {}}
        if "project_id" in data:
            payload["_links"]["project"] = {
                "href": f"/api/v3/projects/{data['project_id']}"
            }
        if "user_id" in data:
            payload["_links"]["principal"] = {
                "href": f"/api/v3/users/{data['user_id']}"
            }
        elif "group_id" in data:
            payload["_links"]["principal"] = {
                "href": f"/api/v3/groups/{data['group_id']}"
            }
        if "role_ids" in data:
            payload["_links"]["roles"] = [
                {"href": f"/api/v3/roles/{r}"} for r in data["role_ids"]
            ]
        elif "role_id" in data:
            payload["_links"]["roles"] = [
                {"href": f"/api/v3/roles/{data['role_id']}"}
            ]
        if "notification_message" in data:
            payload["notificationMessage"] = {"raw": data["notification_message"]}
        return await self._request("POST", "/memberships", payload)

    async def update_membership(self, mem_id: int, data: Dict) -> Dict:
        current = await self._request("GET", f"/memberships/{mem_id}")
        payload = {"lockVersion": current.get("lockVersion", 0)}
        if "role_ids" in data:
            payload.setdefault("_links", {})["roles"] = [
                {"href": f"/api/v3/roles/{r}"} for r in data["role_ids"]
            ]
        elif "role_id" in data:
            payload.setdefault("_links", {})["roles"] = [
                {"href": f"/api/v3/roles/{data['role_id']}"}
            ]
        if "notification_message" in data:
            payload["notificationMessage"] = {"raw": data["notification_message"]}
        return await self._request("PATCH", f"/memberships/{mem_id}", payload)

    async def create_project(self, data: Dict) -> Dict:
        payload = {}
        for f in ("name", "identifier"):
            if f in data:
                payload[f] = data[f]
        if "description" in data:
            payload["description"] = {"raw": data["description"]}
        if "public" in data:
            payload["public"] = data["public"]
        if "status" in data:
            payload["status"] = data["status"]
        if "parent_id" in data:
            payload.setdefault("_links", {})["parent"] = {
                "href": f"/api/v3/projects/{data['parent_id']}"
            }
        return await self._request("POST", "/projects", payload)

    async def update_project(self, project_id: int, data: Dict) -> Dict:
        try:
            current = await self._request("GET", f"/projects/{project_id}")
            lock_version = current.get("lockVersion", 0)
        except Exception:
            lock_version = 0
        payload = {"lockVersion": lock_version}
        for f in ("name", "identifier"):
            if f in data:
                payload[f] = data[f]
        if "description" in data:
            payload["description"] = {"raw": data["description"]}
        if "public" in data:
            payload["public"] = data["public"]
        if "status" in data:
            payload["status"] = data["status"]
        if "parent_id" in data:
            payload.setdefault("_links", {})["parent"] = {
                "href": f"/api/v3/projects/{data['parent_id']}"
            }
        return await self._request("PATCH", f"/projects/{project_id}", payload)

    async def create_version(self, project_id: int, data: Dict) -> Dict:
        payload = {
            "_links": {
                "definingProject": {"href": f"/api/v3/projects/{project_id}"}
            }
        }
        if "name" in data:
            payload["name"] = data["name"]
        if "description" in data:
            payload["description"] = {"raw": data["description"]}
        if "start_date" in data:
            payload["startDate"] = data["start_date"]
        if "end_date" in data:
            payload["endDate"] = data["end_date"]
        if "status" in data:
            payload["status"] = data["status"]
        return await self._request("POST", "/versions", payload)

    async def update_version(self, version_id: int, data: Dict) -> Dict:
        current = await self._request("GET", f"/versions/{version_id}")
        payload = {"lockVersion": current.get("lockVersion", 0)}
        for f in ("name", "status"):
            if f in data:
                payload[f] = data[f]
        if "description" in data:
            payload["description"] = {"raw": data["description"]}
        if "start_date" in data:
            payload["startDate"] = data["start_date"]
        if "end_date" in data:
            payload["endDate"] = data["end_date"]
        return await self._request("PATCH", f"/versions/{version_id}", payload)

    async def create_relation(self, data: Dict) -> Dict:
        payload = {"_links": {}}
        if "from_id" in data:
            payload["_links"]["from"] = {
                "href": f"/api/v3/work_packages/{data['from_id']}"
            }
        if "to_id" in data:
            payload["_links"]["to"] = {
                "href": f"/api/v3/work_packages/{data['to_id']}"
            }
        if "relation_type" in data:
            payload["type"] = data["relation_type"]
        for f in ("lag", "description"):
            if f in data:
                payload[f] = data[f]
        from_id = data.get("from_id")
        return await self._request(
            "POST", f"/work_packages/{from_id}/relations", payload
        )

    async def update_relation(self, relation_id: int, data: Dict) -> Dict:
        current = await self._request("GET", f"/relations/{relation_id}")
        payload = {"lockVersion": current.get("lockVersion", 0)}
        if "relation_type" in data:
            payload["type"] = data["relation_type"]
        for f in ("lag", "description"):
            if f in data:
                payload[f] = data[f]
        return await self._request("PATCH", f"/relations/{relation_id}", payload)


# ═══════════════════════════════════════════════════════════════════════
# Handler Functions — organized by tool
# Each handler: async def handler(client, args) -> str
# ═══════════════════════════════════════════════════════════════════════


# ── project handlers ─────────────────────────────────────────────────


async def h_project_list(client, args):
    filters = None
    if args.get("active_only", True):
        filters = json.dumps([{"active": {"operator": "=", "values": ["t"]}}])
    endpoint = "/projects?pageSize=100"
    if filters:
        endpoint += f"&filters={quote(filters)}"
    result = await client.get(endpoint)
    projects = client._ensure_collection(result)
    if not projects:
        return "No projects found."
    text = f"Found {len(projects)} project(s):\n\n"
    for p in projects:
        text += f"- **{p['name']}** (ID: {p['id']})\n"
        desc = (p.get("description") or {}).get("raw")
        if desc:
            text += f"  {desc}\n"
        text += f"  Status: {'Active' if p.get('active') else 'Inactive'} | Public: {'Yes' if p.get('public') else 'No'}\n\n"
    return text


async def h_project_get(client, args):
    r = await client.get(f"/projects/{args['project_id']}")
    desc = (r.get("description") or {}).get("raw", "No description")
    return (
        f"**Project Details:**\n\n"
        f"- **Name**: {r.get('name', 'N/A')}\n"
        f"- **ID**: #{r.get('id', 'N/A')}\n"
        f"- **Identifier**: {r.get('identifier', 'N/A')}\n"
        f"- **Description**: {desc}\n"
        f"- **Public**: {'Yes' if r.get('public') else 'No'}\n"
        f"- **Status**: {r.get('status', 'N/A')}\n"
        f"- **Created**: {r.get('createdAt', 'N/A')}\n"
        f"- **Updated**: {r.get('updatedAt', 'N/A')}\n"
    )


async def h_project_create(client, args):
    data = {"name": args["name"], "identifier": args["identifier"]}
    for f in ("description", "public", "status", "parent_id"):
        if f in args:
            data[f] = args[f]
    r = await client.create_project(data)
    return (
        f"✅ Project created successfully:\n\n"
        f"- **Name**: {r.get('name')}\n"
        f"- **ID**: #{r.get('id')}\n"
        f"- **Identifier**: {r.get('identifier')}\n"
        f"- **Public**: {'Yes' if r.get('public') else 'No'}\n"
    )


async def h_project_update(client, args):
    pid = args["project_id"]
    data = {
        k: args[k]
        for k in ("name", "identifier", "description", "public", "status", "parent_id")
        if k in args
    }
    if not data:
        return "❌ No fields provided to update."
    r = await client.update_project(pid, data)
    return (
        f"✅ Project #{pid} updated:\n"
        f"- **Name**: {r.get('name')}\n"
        f"- **Identifier**: {r.get('identifier')}\n"
        f"- **Status**: {r.get('status')}\n"
    )


async def h_project_delete(client, args):
    await client.delete_resource(f"/projects/{args['project_id']}")
    return f"✅ Project #{args['project_id']} deleted."


async def h_project_list_types(client, args):
    pid = args.get("project_id")
    endpoint = f"/projects/{pid}/types" if pid else "/types"
    items = await client.get_collection(endpoint)
    if not items:
        return "No work package types found."
    text = "Available work package types:\n\n"
    for t in items:
        text += f"- **{t.get('name')}** (ID: {t.get('id')})"
        if t.get("isDefault"):
            text += " ✓Default"
        if t.get("isMilestone"):
            text += " ✓Milestone"
        text += "\n"
    return text


async def h_project_list_versions(client, args):
    pid = args.get("project_id")
    endpoint = (
        f"/projects/{pid}/versions?pageSize=100"
        if pid
        else "/versions?pageSize=100"
    )
    result = await client.get(endpoint)
    versions = client._ensure_collection(result)
    if not versions:
        return "No versions found."
    text = f"Found {len(versions)} version(s):\n\n"
    for v in versions:
        text += f"- **{v.get('name')}** (ID: {v.get('id')})\n"
        text += f"  Status: {v.get('status', 'Unknown')}"
        if v.get("startDate"):
            text += f" | Start: {v['startDate']}"
        if v.get("endDate"):
            text += f" | End: {v['endDate']}"
        text += "\n"
    return text


async def h_project_list_available_assignees(client, args):
    items = await client.get_collection(
        f"/projects/{args['project_id']}/available_assignees"
    )
    if not items:
        return "No available assignees."
    text = "Available assignees:\n\n"
    for u in items:
        text += f"- **{u.get('name')}** (ID: {u.get('id')})\n"
    return text


async def h_project_copy(client, args):
    r = await client.post(
        f"/projects/{args['source_project_id']}/copy", args.get("payload", {})
    )
    return f"✅ Project copy initiated. New project ID: #{r.get('id', 'pending')}"


# ── work_package handlers ────────────────────────────────────────────


async def h_wp_list(client, args):
    pid = args.get("project_id")
    status = args.get("status", "open")
    offset = args.get("offset")
    page_size = args.get("page_size")

    base = f"/projects/{pid}/work_packages" if pid else "/work_packages"
    params = []
    if status == "open":
        f = json.dumps([{"status_id": {"operator": "o", "values": None}}])
        params.append(f"filters={quote(f)}")
    elif status == "closed":
        f = json.dumps([{"status_id": {"operator": "c", "values": None}}])
        params.append(f"filters={quote(f)}")
    if offset is not None:
        params.append(f"offset={offset}")
    if page_size is not None:
        params.append(f"pageSize={page_size}")

    # A5: Baseline comparison timestamps
    if "timestamps" in args:
        params.append(f"timestamps={quote(args['timestamps'])}")

    endpoint = base + ("?" + "&".join(params) if params else "")
    result = await client.get(endpoint)
    wps = client._ensure_collection(result)
    total = result.get("total", len(wps))
    count = result.get("count", len(wps))

    if not wps:
        return "No work packages found."
    text = f"Found {total} work package(s) (showing {count}):\n\n"
    for wp in wps:
        text += f"- **{wp.get('subject', 'No title')}** (#{wp.get('id')})\n"
        emb = wp.get("_embedded", {})
        parts = []
        if "type" in emb:
            parts.append(f"Type: {emb['type'].get('name')}")
        if "status" in emb:
            parts.append(f"Status: {emb['status'].get('name')}")
        if "project" in emb:
            parts.append(f"Project: {emb['project'].get('name')}")
        if emb.get("assignee"):
            parts.append(f"Assignee: {emb['assignee'].get('name')}")
        if parts:
            text += f"  {' | '.join(parts)}\n"
        if wp.get("percentageDone"):
            text += f"  Progress: {wp['percentageDone']}%\n"
        text += "\n"
    return text


async def h_wp_get(client, args):
    endpoint = f"/work_packages/{args['work_package_id']}"
    # A5: Baseline comparison timestamps
    if "timestamps" in args:
        endpoint += f"?timestamps={quote(args['timestamps'])}"
    r = await client.get(endpoint)
    emb = r.get("_embedded", {})
    text = f"**Work Package Details:**\n\n"
    text += f"- **ID**: #{r.get('id')}\n- **Subject**: {r.get('subject')}\n"
    for key, label in [
        ("type", "Type"),
        ("status", "Status"),
        ("priority", "Priority"),
        ("project", "Project"),
    ]:
        if key in emb:
            text += f"- **{label}**: {emb[key].get('name')}\n"
    if emb.get("assignee"):
        text += f"- **Assignee**: {emb['assignee'].get('name')}\n"
    else:
        text += f"- **Assignee**: Unassigned\n"
    text += f"- **Progress**: {r.get('percentageDone', 0)}%\n"
    text += (
        f"- **Created**: {r.get('createdAt', 'N/A')}\n"
        f"- **Updated**: {r.get('updatedAt', 'N/A')}\n"
    )
    if r.get("startDate"):
        text += f"- **Start Date**: {r['startDate']}\n"
    if r.get("dueDate"):
        text += f"- **Due Date**: {r['dueDate']}\n"
    desc = (r.get("description") or {}).get("raw")
    if desc:
        text += f"\n**Description:**\n{desc}\n"
    return text


async def h_wp_create(client, args):
    data = {
        "project": args["project_id"],
        "subject": args["subject"],
        "type": args["type_id"],
    }
    for f in ("description", "priority_id", "assignee_id"):
        if f in args:
            data[f] = args[f]
    if "start_date" in args:
        data["startDate"] = args["start_date"]
    if "due_date" in args:
        data["dueDate"] = args["due_date"]
    if "date" in args:
        data["date"] = args["date"]

    r = await client.create_work_package(data)
    emb = r.get("_embedded", {})
    text = f"✅ Work package created:\n\n- **ID**: #{r.get('id')}\n- **Subject**: {r.get('subject')}\n"
    if "type" in emb:
        text += f"- **Type**: {emb['type'].get('name')}\n"
    if "status" in emb:
        text += f"- **Status**: {emb['status'].get('name')}\n"
    if "project" in emb:
        text += f"- **Project**: {emb['project'].get('name')}\n"
    return text


async def h_wp_update(client, args):
    wp_id = args["work_package_id"]
    data = {}
    for f in (
        "subject",
        "description",
        "type_id",
        "status_id",
        "priority_id",
        "assignee_id",
        "percentage_done",
    ):
        if f in args:
            data[f] = args[f]
    if "start_date" in args:
        data["startDate"] = args["start_date"]
    if "due_date" in args:
        data["dueDate"] = args["due_date"]
    if "date" in args:
        data["date"] = args["date"]
    if not data:
        return "❌ No fields provided to update."

    r = await client.update_work_package(wp_id, data)
    emb = r.get("_embedded", {})
    text = f"✅ Work package #{wp_id} updated:\n- **Subject**: {r.get('subject')}\n"
    if "status" in emb:
        text += f"- **Status**: {emb['status'].get('name')}\n"
    if "priority" in emb:
        text += f"- **Priority**: {emb['priority'].get('name')}\n"
    if emb.get("assignee"):
        text += f"- **Assignee**: {emb['assignee'].get('name')}\n"
    text += f"- **Progress**: {r.get('percentageDone', 0)}%\n"
    return text


async def h_wp_delete(client, args):
    await client.delete_resource(f"/work_packages/{args['work_package_id']}")
    return f"✅ Work package #{args['work_package_id']} deleted."


async def h_wp_set_parent(client, args):
    r = await client.set_work_package_parent(
        args["work_package_id"], args["parent_id"]
    )
    return (
        f"✅ WP #{args['work_package_id']} is now a child of #{args['parent_id']}. "
        f"Subject: {r.get('subject')}"
    )


async def h_wp_remove_parent(client, args):
    r = await client.remove_work_package_parent(args["work_package_id"])
    return (
        f"✅ WP #{args['work_package_id']} is now top-level. "
        f"Subject: {r.get('subject')}"
    )


async def h_wp_list_children(client, args):
    pid = args["parent_id"]
    desc = args.get("include_descendants", False)
    filter_key = "ancestor" if desc else "parent"
    filters = json.dumps([{filter_key: {"operator": "=", "values": [str(pid)]}}])
    result = await client.get(f"/work_packages?filters={quote(filters)}")
    children = client._ensure_collection(result)
    label = "Descendants" if desc else "Children"
    if not children:
        return f"No {label.lower()} found for WP #{pid}."
    text = f"**{label} of WP #{pid} ({len(children)}):**\n\n"
    for c in children:
        emb = c.get("_embedded", {})
        status = emb.get("status", {}).get("name", "")
        text += f"- **#{c.get('id')}**: {c.get('subject')} [{status}]\n"
    return text


async def h_wp_list_activities(client, args):
    items = await client.get_collection(
        f"/work_packages/{args['work_package_id']}/activities"
    )
    if not items:
        return f"No activities for WP #{args['work_package_id']}."
    text = f"**Activities for WP #{args['work_package_id']} ({len(items)}):**\n\n"
    for a in items:
        user = a.get("_links", {}).get("user", {}).get("title", "System")
        text += f"- **#{a.get('id')}** by {user} at {a.get('createdAt', 'N/A')}\n"
        comment = (a.get("comment") or {}).get("raw")
        if comment:
            text += f"  Comment: {comment}\n"
    return text


async def h_wp_add_comment(client, args):
    payload = {"comment": {"raw": args["comment"]}}
    r = await client.post(
        f"/work_packages/{args['work_package_id']}/activities", payload
    )
    return (
        f"✅ Comment added to WP #{args['work_package_id']} "
        f"(activity #{r.get('id')})"
    )


async def h_wp_list_attachments(client, args):
    items = await client.get_collection(
        f"/work_packages/{args['work_package_id']}/attachments"
    )
    if not items:
        return f"No attachments for WP #{args['work_package_id']}."
    text = f"**Attachments for WP #{args['work_package_id']} ({len(items)}):**\n\n"
    for a in items:
        text += (
            f"- **{a.get('fileName')}** (ID: {a.get('id')}, "
            f"{a.get('fileSize', 0)} bytes)\n"
        )
    return text


async def h_wp_list_watchers(client, args):
    items = await client.get_collection(
        f"/work_packages/{args['work_package_id']}/watchers"
    )
    if not items:
        return f"No watchers for WP #{args['work_package_id']}."
    text = f"**Watchers for WP #{args['work_package_id']} ({len(items)}):**\n\n"
    for w in items:
        text += f"- **{w.get('name')}** (ID: {w.get('id')})\n"
    return text


async def h_wp_add_watcher(client, args):
    payload = {"user": {"href": f"/api/v3/users/{args['user_id']}"}}
    await client.post(
        f"/work_packages/{args['work_package_id']}/watchers", payload
    )
    return (
        f"✅ User #{args['user_id']} added as watcher to "
        f"WP #{args['work_package_id']}"
    )


async def h_wp_remove_watcher(client, args):
    await client.delete_resource(
        f"/work_packages/{args['work_package_id']}/watchers/{args['user_id']}"
    )
    return (
        f"✅ User #{args['user_id']} removed from watchers of "
        f"WP #{args['work_package_id']}"
    )


async def h_wp_list_relations(client, args):
    conditions = []
    if "work_package_id" in args:
        conditions.append(
            {
                "involved": {
                    "operator": "=",
                    "values": [str(args["work_package_id"])],
                }
            }
        )
    if "relation_type" in args:
        conditions.append(
            {"type": {"operator": "=", "values": [args["relation_type"]]}}
        )
    endpoint = "/relations?pageSize=100"
    if conditions:
        endpoint += f"&filters={quote(json.dumps(conditions))}"
    result = await client.get(endpoint)
    rels = client._ensure_collection(result)
    if not rels:
        return "No relations found."
    text = f"**Work Package Relations ({len(rels)}):**\n\n"
    for rel in rels:
        # Try _embedded first (present on single-resource), fall back to _links (collection)
        emb = rel.get("_embedded", {})
        links = rel.get("_links", {})
        from_wp = emb.get("from") or {}
        to_wp = emb.get("to") or {}
        if from_wp.get("id"):
            from_id = from_wp["id"]
            from_subj = from_wp.get("subject", "?")
        else:
            from_link = links.get("from", {})
            from_href = from_link.get("href", "")
            from_id = from_href.rsplit("/", 1)[-1] if from_href else "?"
            from_subj = from_link.get("title", "?")
        if to_wp.get("id"):
            to_id = to_wp["id"]
            to_subj = to_wp.get("subject", "?")
        else:
            to_link = links.get("to", {})
            to_href = to_link.get("href", "")
            to_id = to_href.rsplit("/", 1)[-1] if to_href else "?"
            to_subj = to_link.get("title", "?")
        text += (
            f"- **#{rel.get('id')}**: {rel.get('type')} — "
            f"#{from_id} ({from_subj}) → "
            f"#{to_id} ({to_subj})\n"
        )
        if rel.get("lag"):
            text += f"  Lag: {rel['lag']} days\n"
    return text


async def h_wp_create_relation(client, args):
    data = {
        "from_id": args["from_id"],
        "to_id": args["to_id"],
        "relation_type": args["relation_type"],
    }
    for f in ("lag", "description"):
        if f in args:
            data[f] = args[f]
    r = await client.create_relation(data)
    text = (
        f"✅ Relation created: #{r.get('id')} ({r.get('type')}) "
        f"WP#{args['from_id']} → WP#{args['to_id']}"
    )
    if r.get("lag"):
        text += f" (lag: {r['lag']} days)"
    return text


async def h_wp_get_relation(client, args):
    r = await client.get(f"/relations/{args['relation_id']}")
    emb = r.get("_embedded", {})
    from_wp = emb.get("from", {})
    to_wp = emb.get("to", {})
    return (
        f"**Relation #{r.get('id')}:**\n"
        f"- Type: {r.get('type')} (reverse: {r.get('reverseType')})\n"
        f"- From: #{from_wp.get('id')} — {from_wp.get('subject')}\n"
        f"- To: #{to_wp.get('id')} — {to_wp.get('subject')}\n"
        f"- Lag: {r.get('lag', 0)} days\n"
    )


async def h_wp_update_relation(client, args):
    rid = args["relation_id"]
    data = {
        k: args[k] for k in ("relation_type", "lag", "description") if k in args
    }
    if not data:
        return "❌ No fields provided to update."
    r = await client.update_relation(rid, data)
    return f"✅ Relation #{rid} updated. Type: {r.get('type')}, Lag: {r.get('lag', 0)}"


async def h_wp_delete_relation(client, args):
    await client.delete_resource(f"/relations/{args['relation_id']}")
    return f"✅ Relation #{args['relation_id']} deleted."


async def h_wp_list_available_watchers(client, args):
    items = await client.get_collection(
        f"/work_packages/{args['work_package_id']}/available_watchers"
    )
    if not items:
        return "No available watchers."
    text = "Available watchers:\n\n"
    for u in items:
        text += f"- **{u.get('name')}** (ID: {u.get('id')})\n"
    return text


async def h_wp_list_available_relation_candidates(client, args):
    endpoint = (
        f"/work_packages/{args['work_package_id']}/available_relation_candidates"
    )
    if args.get("query"):
        endpoint += f"?query={quote(args['query'])}"
    items = await client.get_collection(endpoint)
    if not items:
        return "No relation candidates found."
    text = f"Available relation candidates ({len(items)}):\n\n"
    for wp in items:
        text += f"- **#{wp.get('id')}**: {wp.get('subject')}\n"
    return text


# ── time_entry handlers ──────────────────────────────────────────────


async def h_te_list(client, args):
    filters = []
    if "work_package_id" in args:
        filters.append(
            {
                "workPackage": {
                    "operator": "=",
                    "values": [str(args["work_package_id"])],
                }
            }
        )
    if "user_id" in args:
        filters.append(
            {"user": {"operator": "=", "values": [str(args["user_id"])]}}
        )
    endpoint = "/time_entries"
    if filters:
        endpoint += f"?filters={quote(json.dumps(filters))}"
    result = await client.get(endpoint)
    entries = client._ensure_collection(result)
    if not entries:
        return "No time entries found."
    text = f"Found {len(entries)} time entry(ies):\n\n"
    for e in entries:
        hours = _parse_iso_duration_hours(e.get("hours", "PT0H"))
        emb = e.get("_embedded", {})
        wp_name = emb.get("workPackage", {}).get("subject", "?")
        user_name = emb.get("user", {}).get("name", "?")
        text += (
            f"- **#{e.get('id')}**: {hours}h on {e.get('spentOn', '?')} "
            f"by {user_name} — {wp_name}\n"
        )
        comment = (e.get("comment") or {}).get("raw")
        if comment:
            text += f"  Comment: {comment}\n"
    return text


async def h_te_get(client, args):
    r = await client.get(f"/time_entries/{args['time_entry_id']}")
    hours = _parse_iso_duration_hours(r.get("hours", "PT0H"))
    emb = r.get("_embedded", {})
    text = f"**Time Entry #{r.get('id')}:**\n"
    text += f"- Hours: {hours}\n- Date: {r.get('spentOn')}\n"
    if "workPackage" in emb:
        text += f"- Work Package: {emb['workPackage'].get('subject')}\n"
    if "user" in emb:
        text += f"- User: {emb['user'].get('name')}\n"
    if "activity" in emb:
        text += f"- Activity: {emb['activity'].get('name')}\n"
    return text


async def h_te_create(client, args):
    data = {
        "work_package_id": args["work_package_id"],
        "hours": args["hours"],
        "spent_on": args["spent_on"],
    }
    for f in ("comment", "activity_id"):
        if f in args:
            data[f] = args[f]
    r = await client.create_time_entry(data)
    hours = _parse_iso_duration_hours(r.get("hours", "PT0H"))
    return f"✅ Time entry created: #{r.get('id')} — {hours}h on {r.get('spentOn')}"


async def h_te_update(client, args):
    te_id = args["time_entry_id"]
    data = {
        k: args[k]
        for k in ("hours", "spent_on", "comment", "activity_id")
        if k in args
    }
    if not data:
        return "❌ No fields provided to update."
    r = await client.update_time_entry(te_id, data)
    hours = _parse_iso_duration_hours(r.get("hours", "PT0H"))
    return f"✅ Time entry #{te_id} updated: {hours}h on {r.get('spentOn')}"


async def h_te_delete(client, args):
    await client.delete_resource(f"/time_entries/{args['time_entry_id']}")
    return f"✅ Time entry #{args['time_entry_id']} deleted."


async def h_te_list_activities(client, args):
    try:
        items = await client.get_collection("/time_entries/activities")
        if not items:
            raise Exception("empty")
    except Exception:
        return (
            "Available time entry activities (defaults):\n\n"
            "- **Management** (ID: 1)\n"
            "- **Specification** (ID: 2)\n"
            "- **Development** (ID: 3)\n"
            "- **Testing** (ID: 4)\n"
        )
    text = "Available time entry activities:\n\n"
    for a in items:
        text += f"- **{a.get('name')}** (ID: {a.get('id')})"
        if a.get("isDefault"):
            text += " ✓Default"
        text += "\n"
    return text


# ── membership handlers ──────────────────────────────────────────────


async def h_mem_list(client, args):
    endpoint = "/memberships?pageSize=100"
    filters = []
    if "project_id" in args:
        filters.append(
            {"project": {"operator": "=", "values": [str(args["project_id"])]}}
        )
    if "user_id" in args:
        filters.append(
            {"principal": {"operator": "=", "values": [str(args["user_id"])]}}
        )
    if filters:
        endpoint += f"&filters={quote(json.dumps(filters))}"
    result = await client.get(endpoint)
    mems = client._ensure_collection(result)
    if not mems:
        return "No memberships found."
    text = f"Found {len(mems)} membership(s):\n\n"
    for m in mems:
        links = m.get("_links", {})
        principal = links.get("principal", {}).get("title", "?")
        project = links.get("project", {}).get("title", "?")
        roles = ", ".join(r.get("title", "?") for r in links.get("roles", []))
        text += f"- **#{m.get('id')}**: {principal} in {project} — {roles}\n"
    return text


async def h_mem_get(client, args):
    r = await client.get(f"/memberships/{args['membership_id']}")
    links = r.get("_links", {})
    principal = links.get("principal", {}).get("title", "?")
    project = links.get("project", {}).get("title", "?")
    roles = ", ".join(ro.get("title", "?") for ro in links.get("roles", []))
    return (
        f"**Membership #{r.get('id')}:**\n"
        f"- Principal: {principal}\n"
        f"- Project: {project}\n"
        f"- Roles: {roles}\n"
    )


async def h_mem_create(client, args):
    data = {"project_id": args["project_id"]}
    if "user_id" in args:
        data["user_id"] = args["user_id"]
    elif "group_id" in args:
        data["group_id"] = args["group_id"]
    else:
        return "❌ Either user_id or group_id is required."
    if "role_ids" in args:
        data["role_ids"] = args["role_ids"]
    elif "role_id" in args:
        data["role_id"] = args["role_id"]
    else:
        return "❌ Either role_ids or role_id is required."
    if "notification_message" in args:
        data["notification_message"] = args["notification_message"]
    r = await client.create_membership(data)
    emb = r.get("_embedded", {})
    principal = emb.get("principal", {}).get("name", "?")
    project = emb.get("project", {}).get("name", "?")
    return f"✅ Membership #{r.get('id')} created: {principal} in {project}"


async def h_mem_update(client, args):
    mid = args["membership_id"]
    data = {}
    for f in ("role_ids", "role_id", "notification_message"):
        if f in args:
            data[f] = args[f]
    if not data:
        return "❌ No fields provided to update."
    await client.update_membership(mid, data)
    return f"✅ Membership #{mid} updated."


async def h_mem_delete(client, args):
    await client.delete_resource(f"/memberships/{args['membership_id']}")
    return f"✅ Membership #{args['membership_id']} deleted."


async def h_mem_list_project_members(client, args):
    pid = args["project_id"]
    f = json.dumps([{"project": {"operator": "=", "values": [str(pid)]}}])
    endpoint = f"/memberships?pageSize=100&filters={quote(f)}"
    result = await client.get(endpoint)
    mems = client._ensure_collection(result)
    if not mems:
        return f"No members found for project #{pid}."
    text = f"**Project #{pid} Members ({len(mems)}):**\n\n"
    for m in mems:
        links = m.get("_links", {})
        name = links.get("principal", {}).get("title", "?")
        roles = ", ".join(r.get("title", "?") for r in links.get("roles", []))
        text += f"- **{name}**: {roles}\n"
    return text


async def h_mem_list_user_projects(client, args):
    uid = args["user_id"]
    f = json.dumps([{"principal": {"operator": "=", "values": [str(uid)]}}])
    endpoint = f"/memberships?pageSize=100&filters={quote(f)}"
    result = await client.get(endpoint)
    mems = client._ensure_collection(result)
    if not mems:
        return f"No projects found for user #{uid}."
    text = f"**User #{uid} Projects ({len(mems)}):**\n\n"
    for m in mems:
        links = m.get("_links", {})
        proj = links.get("project", {}).get("title", "?")
        roles = ", ".join(r.get("title", "?") for r in links.get("roles", []))
        text += f"- **{proj}**: {roles}\n"
    return text


# ── principal handlers ───────────────────────────────────────────────


async def h_principal_list_users(client, args):
    endpoint = "/users?pageSize=100"
    if args.get("active_only", True):
        f = json.dumps([{"status": {"operator": "=", "values": ["active"]}}])
        endpoint += f"&filters={quote(f)}"
    result = await client.get(endpoint)
    users = client._ensure_collection(result)
    if not users:
        return "No users found."
    text = f"Found {len(users)} user(s):\n\n"
    for u in users:
        text += (
            f"- **{u.get('name')}** (ID: {u.get('id')}) — "
            f"{u.get('email', 'N/A')} [{u.get('status')}]"
        )
        if u.get("admin"):
            text += " ✓Admin"
        text += "\n"
    return text


async def h_principal_get_user(client, args):
    r = await client.get(f"/users/{args['user_id']}")
    return (
        f"**User #{r.get('id')}:**\n"
        f"- Name: {r.get('name')}\n"
        f"- Email: {r.get('email', 'N/A')}\n"
        f"- Status: {r.get('status')}\n"
        f"- Admin: {'Yes' if r.get('admin') else 'No'}\n"
        f"- Language: {r.get('language', 'N/A')}\n"
        f"- Created: {r.get('createdAt')}\n"
        f"- Updated: {r.get('updatedAt')}\n"
    )


async def h_principal_create_user(client, args):
    r = await client.post("/users", args.get("payload", {}))
    return f"✅ User created: #{r.get('id')} — {r.get('name')} ({r.get('email')})"


async def h_principal_update_user(client, args):
    r = await client.patch(f"/users/{args['user_id']}", args.get("payload", {}))
    return f"✅ User #{args['user_id']} updated: {r.get('name')}"


async def h_principal_delete_user(client, args):
    await client.delete_resource(f"/users/{args['user_id']}")
    return f"✅ User #{args['user_id']} deleted."


async def h_principal_lock_user(client, args):
    await client.post(f"/users/{args['user_id']}/lock")
    return f"✅ User #{args['user_id']} locked."


async def h_principal_unlock_user(client, args):
    await client.delete_resource(f"/users/{args['user_id']}/lock")
    return f"✅ User #{args['user_id']} unlocked."


async def h_principal_list_groups(client, args):
    items = await client.get_collection("/groups")
    if not items:
        return "No groups found."
    text = f"Found {len(items)} group(s):\n\n"
    for g in items:
        text += f"- **{g.get('name')}** (ID: {g.get('id')})\n"
    return text


async def h_principal_get_group(client, args):
    r = await client.get(f"/groups/{args['group_id']}")
    return f"**Group #{r.get('id')}:** {r.get('name')}\n"


async def h_principal_create_group(client, args):
    r = await client.post("/groups", args.get("payload", {}))
    return f"✅ Group created: #{r.get('id')} — {r.get('name')}"


async def h_principal_update_group(client, args):
    await client.patch(f"/groups/{args['group_id']}", args.get("payload", {}))
    return f"✅ Group #{args['group_id']} updated."


async def h_principal_delete_group(client, args):
    await client.delete_resource(f"/groups/{args['group_id']}")
    return f"✅ Group #{args['group_id']} deleted."


async def h_principal_list_roles(client, args):
    result = await client.get("/roles?pageSize=100")
    roles = client._ensure_collection(result)
    if not roles:
        return "No roles found."
    text = f"Available roles ({len(roles)}):\n\n"
    for r in roles:
        text += f"- **{r.get('name')}** (ID: {r.get('id')})\n"
    return text


async def h_principal_get_role(client, args):
    r = await client.get(f"/roles/{args['role_id']}")
    text = f"**Role #{r.get('id')}:** {r.get('name')}\n"
    if r.get("permissions"):
        text += f"  {len(r['permissions'])} permissions\n"
    return text


async def h_principal_list_principals(client, args):
    items = await client.get_collection("/principals?pageSize=100")
    if not items:
        return "No principals found."
    text = f"Found {len(items)} principal(s):\n\n"
    for p in items:
        text += (
            f"- **{p.get('name')}** (ID: {p.get('id')}, "
            f"type: {p.get('_type', '?')})\n"
        )
    return text


# ── version handlers ─────────────────────────────────────────────────


async def h_version_list(client, args):
    return await h_project_list_versions(client, args)


async def h_version_get(client, args):
    r = await client.get(f"/versions/{args['version_id']}")
    text = f"**Version #{r.get('id')}:** {r.get('name')}\n"
    text += f"- Status: {r.get('status')}\n"
    if r.get("startDate"):
        text += f"- Start: {r['startDate']}\n"
    if r.get("endDate"):
        text += f"- End: {r['endDate']}\n"
    desc = (r.get("description") or {}).get("raw")
    if desc:
        text += f"- Description: {desc}\n"
    return text


async def h_version_create(client, args):
    data = {"name": args["name"]}
    for f in ("description", "start_date", "end_date", "status"):
        if f in args:
            data[f] = args[f]
    r = await client.create_version(args["project_id"], data)
    return (
        f"✅ Version created: #{r.get('id')} — "
        f"{r.get('name')} [{r.get('status')}]"
    )


async def h_version_update(client, args):
    vid = args["version_id"]
    data = {
        k: args[k]
        for k in ("name", "description", "start_date", "end_date", "status")
        if k in args
    }
    if not data:
        return "❌ No fields provided to update."
    r = await client.update_version(vid, data)
    return f"✅ Version #{vid} updated: {r.get('name')} [{r.get('status')}]"


async def h_version_delete(client, args):
    await client.delete_resource(f"/versions/{args['version_id']}")
    return f"✅ Version #{args['version_id']} deleted."


async def h_version_list_projects(client, args):
    items = await client.get_collection(
        f"/versions/{args['version_id']}/projects"
    )
    if not items:
        return "No projects share this version."
    text = f"Projects sharing version #{args['version_id']}:\n\n"
    for p in items:
        text += f"- **{p.get('name')}** (ID: {p.get('id')})\n"
    return text


# ── query_view handlers ──────────────────────────────────────────────


async def h_qv_list_queries(client, args):
    items = await client.get_collection("/queries?pageSize=100")
    if not items:
        return "No queries found."
    text = f"Found {len(items)} query(ies):\n\n"
    for q in items:
        text += f"- **{q.get('name')}** (ID: {q.get('id')})"
        if q.get("starred"):
            text += " ★"
        if q.get("public"):
            text += " [public]"
        text += "\n"
    return text


async def h_qv_get_query(client, args):
    r = await client.get(f"/queries/{args['query_id']}")
    return (
        f"**Query #{r.get('id')}:** {r.get('name')}\n"
        f"- Public: {r.get('public')}\n"
        f"- Starred: {r.get('starred')}\n"
    )


async def h_qv_create_query(client, args):
    r = await client.post("/queries", args.get("payload", {}))
    return f"✅ Query created: #{r.get('id')} — {r.get('name')}"


async def h_qv_update_query(client, args):
    await client.patch(
        f"/queries/{args['query_id']}", args.get("payload", {})
    )
    return f"✅ Query #{args['query_id']} updated."


async def h_qv_delete_query(client, args):
    await client.delete_resource(f"/queries/{args['query_id']}")
    return f"✅ Query #{args['query_id']} deleted."


async def h_qv_star(client, args):
    await client.patch(f"/queries/{args['query_id']}/star")
    return f"✅ Query #{args['query_id']} starred."


async def h_qv_unstar(client, args):
    await client.patch(f"/queries/{args['query_id']}/unstar")
    return f"✅ Query #{args['query_id']} unstarred."


async def h_qv_get_default(client, args):
    pid = args.get("project_id")
    endpoint = (
        f"/projects/{pid}/queries/default" if pid else "/queries/default"
    )
    r = await client.get(endpoint)
    return f"**Default Query:** {r.get('name')} (ID: {r.get('id')})\n"


# ── notification handlers ───────────────────────────────────────────


async def h_notif_list(client, args):
    items = await client.get_collection("/notifications?pageSize=100")
    if not items:
        return "No notifications."
    text = f"Found {len(items)} notification(s):\n\n"
    for n in items:
        reason = n.get("reason", "?")
        read = "read" if n.get("readIAN") else "unread"
        text += f"- **#{n.get('id')}**: {reason} [{read}]\n"
    return text


async def h_notif_get(client, args):
    r = await client.get(f"/notifications/{args['notification_id']}")
    return (
        f"**Notification #{r.get('id')}:**\n"
        f"- Reason: {r.get('reason')}\n"
        f"- Read: {r.get('readIAN')}\n"
        f"- Created: {r.get('createdAt')}\n"
    )


async def h_notif_get_detail(client, args):
    r = await client.get(
        f"/notifications/{args['notification_id']}/details/{args['detail_id']}"
    )
    return f"**Notification Detail:**\n{json.dumps(r, indent=2)[:2000]}"


async def h_notif_mark_read(client, args):
    await client.post(f"/notifications/{args['notification_id']}/read_ian")
    return f"✅ Notification #{args['notification_id']} marked as read."


async def h_notif_mark_unread(client, args):
    await client.post(f"/notifications/{args['notification_id']}/unread_ian")
    return f"✅ Notification #{args['notification_id']} marked as unread."


async def h_notif_mark_all_read(client, args):
    await client.post("/notifications/read_ian")
    return "✅ All notifications marked as read."


async def h_notif_mark_all_unread(client, args):
    await client.post("/notifications/unread_ian")
    return "✅ All notifications marked as unread."


# ── artifact handlers ────────────────────────────────────────────────


async def h_art_list_news(client, args):
    items = await client.get_collection("/news?pageSize=100")
    if not items:
        return "No news found."
    text = f"Found {len(items)} news item(s):\n\n"
    for n in items:
        text += (
            f"- **{n.get('title')}** (ID: {n.get('id')}) — "
            f"{n.get('createdAt', '?')}\n"
        )
    return text


async def h_art_get_news(client, args):
    r = await client.get(f"/news/{args['news_id']}")
    desc = (r.get("description") or {}).get("raw", "")
    return f"**News #{r.get('id')}:** {r.get('title')}\n{desc}\n"


async def h_art_create_news(client, args):
    r = await client.post("/news", args.get("payload", {}))
    return f"✅ News created: #{r.get('id')} — {r.get('title')}"


async def h_art_update_news(client, args):
    await client.patch(f"/news/{args['news_id']}", args.get("payload", {}))
    return f"✅ News #{args['news_id']} updated."


async def h_art_delete_news(client, args):
    await client.delete_resource(f"/news/{args['news_id']}")
    return f"✅ News #{args['news_id']} deleted."


async def h_art_get_wiki_page(client, args):
    r = await client.get(f"/wiki_pages/{args['wiki_page_id']}")
    return f"**Wiki Page #{r.get('id')}:** {r.get('title', '?')}\n"


async def h_art_get_document(client, args):
    r = await client.get(f"/documents/{args['document_id']}")
    return f"**Document #{r.get('id')}:** {r.get('title', '?')}\n"


async def h_art_list_documents(client, args):
    items = await client.get_collection("/documents?pageSize=100")
    if not items:
        return "No documents found."
    text = f"Found {len(items)} document(s):\n\n"
    for d in items:
        text += f"- **{d.get('title', '?')}** (ID: {d.get('id')})\n"
    return text


async def h_art_get_meeting(client, args):
    r = await client.get(f"/meetings/{args['meeting_id']}")
    return f"**Meeting #{r.get('id')}:** {r.get('title', '?')}\n"


async def h_art_get_attachment(client, args):
    r = await client.get(f"/attachments/{args['attachment_id']}")
    return (
        f"**Attachment #{r.get('id')}:** {r.get('fileName')} "
        f"({r.get('fileSize', 0)} bytes)\n"
    )


async def h_art_delete_attachment(client, args):
    await client.delete_resource(f"/attachments/{args['attachment_id']}")
    return f"✅ Attachment #{args['attachment_id']} deleted."


# ── integration handlers ────────────────────────────────────────────


async def h_int_test_connection(client, args):
    r = await client.get("")
    text = "✅ API connection successful!\n"
    if client.proxy:
        text += f"Connected via proxy: {client.proxy}\n"
    text += (
        f"Instance: {r.get('instanceName', '?')}\n"
        f"Version: {r.get('coreVersion', '?')}\n"
    )
    return text


async def h_int_check_permissions(client, args):
    r = await client.get("/users/me")
    if not r:
        return "❌ Unable to retrieve user permissions."
    text = (
        f"**Current User:**\n"
        f"- Name: {r.get('name')}\n"
        f"- ID: {r.get('id')}\n"
        f"- Email: {r.get('email', 'N/A')}\n"
        f"- Admin: {'Yes' if r.get('admin') else 'No'}\n"
        f"- Status: {r.get('status')}\n"
        f"- Language: {r.get('language', 'N/A')}\n"
    )
    if "_links" in r:
        actions = [
            k for k in r["_links"] if k not in ("self", "showUser")
        ]
        if actions:
            text += f"\nAvailable actions: {', '.join(actions)}\n"
    return text


async def h_int_list_statuses(client, args):
    result = await client.get("/statuses?pageSize=100")
    items = client._ensure_collection(result)
    if not items:
        return "No statuses found."
    text = "Available statuses:\n\n"
    for s in items:
        text += f"- **{s.get('name')}** (ID: {s.get('id')})"
        if s.get("isDefault"):
            text += " ✓Default"
        if s.get("isClosed"):
            text += " ✓Closed"
        text += f" (position: {s.get('position', 'N/A')})\n"
    return text


async def h_int_get_status(client, args):
    r = await client.get(f"/statuses/{args['status_id']}")
    return (
        f"**Status #{r.get('id')}:** {r.get('name')} "
        f"(default: {r.get('isDefault')}, closed: {r.get('isClosed')})\n"
    )


async def h_int_list_priorities(client, args):
    result = await client.get("/priorities?pageSize=100")
    items = client._ensure_collection(result)
    if not items:
        return "No priorities found."
    text = "Available priorities:\n\n"
    for p in items:
        text += f"- **{p.get('name')}** (ID: {p.get('id')})"
        if p.get("isDefault"):
            text += " ✓Default"
        if p.get("isActive"):
            text += " ✓Active"
        text += f" (position: {p.get('position', 'N/A')})\n"
    return text


async def h_int_get_priority(client, args):
    r = await client.get(f"/priorities/{args['priority_id']}")
    return (
        f"**Priority #{r.get('id')}:** {r.get('name')} "
        f"(default: {r.get('isDefault')})\n"
    )


async def h_int_list_types(client, args):
    return await h_project_list_types(client, args)


async def h_int_get_type(client, args):
    r = await client.get(f"/types/{args['type_id']}")
    return (
        f"**Type #{r.get('id')}:** {r.get('name')} "
        f"(milestone: {r.get('isMilestone')}, default: {r.get('isDefault')})\n"
    )


async def h_int_get_category(client, args):
    r = await client.get(f"/categories/{args['category_id']}")
    return f"**Category #{r.get('id')}:** {r.get('name')}\n"


async def h_int_list_categories(client, args):
    items = await client.get_collection(
        f"/projects/{args['project_id']}/categories"
    )
    if not items:
        return "No categories found."
    text = f"Categories for project #{args['project_id']}:\n\n"
    for c in items:
        text += f"- **{c.get('name')}** (ID: {c.get('id')})\n"
    return text


async def h_int_get_custom_action(client, args):
    r = await client.get(f"/custom_actions/{args['custom_action_id']}")
    return (
        f"**Custom Action #{r.get('id')}:** {r.get('name')}\n"
        f"- Description: {r.get('description', 'N/A')}\n"
    )


async def h_int_execute_custom_action(client, args):
    payload = {
        "lockVersion": args.get("lock_version", 0),
        "_links": {
            "workPackage": {
                "href": f"/api/v3/work_packages/{args['work_package_id']}"
            }
        },
    }
    await client.post(
        f"/custom_actions/{args['custom_action_id']}/execute", payload
    )
    return (
        f"✅ Custom action #{args['custom_action_id']} executed on "
        f"WP #{args['work_package_id']}"
    )


async def h_int_get_configuration(client, args):
    r = await client.get("/configuration")
    return f"**Configuration:**\n{json.dumps(r, indent=2)[:3000]}"


async def h_int_render_markdown(client, args):
    r = await client.post_text("/render/markdown", args["text"])
    return f"**Rendered HTML:**\n{r.get('html', str(r))}"


# ── A1: Day/Schedule handlers (integration tool) ─────────────────────


async def h_int_list_days(client, args):
    """List days with optional filters for date range and working status."""
    filters = []
    from_date = args.get("from_date")
    to_date = args.get("to_date")
    if from_date and to_date:
        filters.append({"date": {"operator": "<>d", "values": [from_date, to_date]}})
    elif from_date:
        filters.append({"date": {"operator": "<>d", "values": [from_date, "2099-12-31"]}})
    elif to_date:
        filters.append({"date": {"operator": "<>d", "values": ["2000-01-01", to_date]}})
    if "working" in args:
        val = "t" if args["working"] else "f"
        filters.append({"working": {"operator": "=", "values": [val]}})
    endpoint = "/days?pageSize=100"
    if filters:
        endpoint += f"&filters={quote(json.dumps(filters))}"
    result = await client.get(endpoint)
    days = client._ensure_collection(result)
    if not days:
        return "No days found matching filters."
    text = f"Found {len(days)} day(s):\n\n"
    for d in days:
        working = "Working" if d.get("working") else "Non-working"
        name = d.get("name", "")
        text += f"- **{d.get('date')}** ({name}) — {working}\n"
    return text


async def h_int_get_day(client, args):
    """Get info for a single day."""
    date_val = args["date"]
    filters = [{"date": {"operator": "<>d", "values": [date_val, date_val]}}]
    endpoint = f"/days?filters={quote(json.dumps(filters))}&pageSize=1"
    result = await client.get(endpoint)
    days = client._ensure_collection(result)
    if not days:
        return f"No data found for {date_val}."
    d = days[0]
    working = "Working" if d.get("working") else "Non-working"
    return (
        f"**Day: {d.get('date')}**\n"
        f"- Name: {d.get('name', 'N/A')}\n"
        f"- Working: {working}\n"
    )


async def h_int_list_non_working_days(client, args):
    """List non-working days (holidays, not weekends)."""
    endpoint = "/days/non_working?pageSize=100"
    filters = []
    from_date = args.get("from_date")
    to_date = args.get("to_date")
    if from_date and to_date:
        filters.append({"date": {"operator": "<>d", "values": [from_date, to_date]}})
    elif from_date:
        filters.append({"date": {"operator": "<>d", "values": [from_date, "2099-12-31"]}})
    elif to_date:
        filters.append({"date": {"operator": "<>d", "values": ["2000-01-01", to_date]}})
    if filters:
        endpoint += f"&filters={quote(json.dumps(filters))}"
    result = await client.get(endpoint)
    days = client._ensure_collection(result)
    if not days:
        return "No non-working days found."
    text = f"Found {len(days)} non-working day(s):\n\n"
    for d in days:
        text += f"- **{d.get('date')}**: {d.get('name', 'N/A')}\n"
    return text


async def h_int_get_week_schedule(client, args):
    """Get weekly schedule (Mon-Sun working/non-working flags)."""
    r = await client.get("/days/week")
    elements = r.get("_embedded", {}).get("elements", [r] if "day" in r else [])
    if not elements:
        return f"**Week Schedule:**\n{json.dumps(r, indent=2)[:2000]}"
    text = "**Week Schedule:**\n\n"
    for d in elements:
        working = "Working" if d.get("working") else "Non-working"
        text += f"- **{d.get('day', d.get('name', '?'))}**: {working}\n"
    return text


# ── A2: Budget handlers (project tool) ───────────────────────────────


async def h_project_list_budgets(client, args):
    """List budgets for a project."""
    pid = args["project_id"]
    try:
        items = await client.get_collection(f"/projects/{pid}/budgets")
    except Exception as e:
        if "403" in str(e):
            return f"Budgets module is not enabled for project #{pid}. Enable it in Project Settings > Modules."
        raise
    if not items:
        return f"No budgets found for project #{pid}."
    text = f"**Budgets for Project #{pid} ({len(items)}):**\n\n"
    for b in items:
        text += f"- **{b.get('subject', 'N/A')}** (ID: {b.get('id')})\n"
        if b.get("spentUnits") is not None:
            text += f"  Spent: {b.get('spentUnits')}\n"
        if b.get("plannedUnits") is not None:
            text += f"  Planned: {b.get('plannedUnits')}\n"
    return text


async def h_project_get_budget(client, args):
    """Get a single budget by ID."""
    r = await client.get(f"/budgets/{args['budget_id']}")
    text = f"**Budget #{r.get('id')}:** {r.get('subject', 'N/A')}\n"
    desc = (r.get("description") or {}).get("raw")
    if desc:
        text += f"- Description: {desc}\n"
    text += f"- Created: {r.get('createdAt', 'N/A')}\n"
    text += f"- Updated: {r.get('updatedAt', 'N/A')}\n"
    return text


# ── A3: Attachment Upload handler (work_package tool) ─────────────────


async def h_wp_add_attachment(client, args):
    """Upload an attachment to a work package via multipart form-data."""
    wp_id = args["work_package_id"]
    file_name = args["file_name"]
    content = args.get("content", "")
    content_type = args.get("content_type", "application/octet-stream")

    url = f"{client.base_url}/api/v3/work_packages/{wp_id}/attachments"
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=30)

    # Build multipart form
    form = aiohttp.FormData()
    form.add_field(
        "file",
        content.encode("utf-8") if isinstance(content, str) else content,
        filename=file_name,
        content_type=content_type,
    )
    if "description" in args:
        form.add_field(
            "metadata",
            json.dumps({"description": {"raw": args["description"]}}),
            content_type="application/json",
        )

    headers = {
        "Authorization": client.headers["Authorization"],
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout
    ) as session:
        request_params = {"url": url, "headers": headers, "data": form}
        if client.proxy:
            request_params["proxy"] = client.proxy
        async with session.post(**request_params) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Upload failed ({response.status}): {text[:500]}")
            r = await response.json()
            return (
                f"✅ Attachment uploaded to WP #{wp_id}:\n"
                f"- File: {r.get('fileName')}\n"
                f"- ID: {r.get('id')}\n"
                f"- Size: {r.get('fileSize', 0)} bytes\n"
            )


# ── A4: File Link handlers (work_package + artifact tools) ────────────


async def h_wp_list_file_links(client, args):
    """List file links for a work package."""
    wp_id = args["work_package_id"]
    items = await client.get_collection(
        f"/work_packages/{wp_id}/file_links"
    )
    if not items:
        return f"No file links for WP #{wp_id}."
    text = f"**File Links for WP #{wp_id} ({len(items)}):**\n\n"
    for fl in items:
        origin = fl.get("originData", {})
        text += (
            f"- **{origin.get('name', 'N/A')}** (ID: {fl.get('id')})\n"
            f"  MIME: {origin.get('mimeType', '?')} | "
            f"Modified: {origin.get('lastModifiedAt', '?')}\n"
        )
    return text


async def h_wp_add_file_links(client, args):
    """Add file links to a work package (bulk, up to 20)."""
    wp_id = args["work_package_id"]
    file_links = args.get("file_links", [])
    if not file_links:
        return "❌ No file_links provided."

    # Build payload per OP API spec
    payload = {
        "_type": "Collection",
        "_embedded": {
            "elements": file_links[:20]  # API limit of 20
        },
    }
    r = await client.post(
        f"/work_packages/{wp_id}/file_links", payload
    )
    created = r.get("_embedded", {}).get("elements", [])
    text = f"✅ {len(created)} file link(s) added to WP #{wp_id}:\n\n"
    for fl in created:
        origin = fl.get("originData", {})
        text += f"- **{origin.get('name', '?')}** (ID: {fl.get('id')})\n"
    return text


async def h_art_get_file_link(client, args):
    """Get a file link by ID."""
    r = await client.get(f"/file_links/{args['file_link_id']}")
    origin = r.get("originData", {})
    return (
        f"**File Link #{r.get('id')}:**\n"
        f"- Name: {origin.get('name', 'N/A')}\n"
        f"- MIME: {origin.get('mimeType', '?')}\n"
        f"- Size: {origin.get('size', '?')} bytes\n"
        f"- Last Modified: {origin.get('lastModifiedAt', '?')}\n"
        f"- Created By: {origin.get('createdByName', '?')}\n"
    )


async def h_art_open_file_link(client, args):
    """Get the open location URL for a file link."""
    r = await client.get(f"/file_links/{args['file_link_id']}/open")
    return (
        f"**Open File Link #{args['file_link_id']}:**\n"
        f"{json.dumps(r, indent=2)[:2000]}"
    )


async def h_art_download_file_link(client, args):
    """Get the download location URL for a file link."""
    r = await client.get(f"/file_links/{args['file_link_id']}/download")
    return (
        f"**Download File Link #{args['file_link_id']}:**\n"
        f"{json.dumps(r, indent=2)[:2000]}"
    )


async def h_art_delete_file_link(client, args):
    """Delete a file link."""
    await client.delete_resource(f"/file_links/{args['file_link_id']}")
    return f"✅ File link #{args['file_link_id']} deleted."


# ── A6: Custom Field/Option handlers (integration tool) ──────────────


async def h_int_get_custom_option(client, args):
    """Get a custom option (allowed value for list-type custom fields)."""
    r = await client.get(f"/custom_options/{args['custom_option_id']}")
    return (
        f"**Custom Option #{r.get('id')}:**\n"
        f"- Value: {r.get('value', 'N/A')}\n"
    )


async def h_int_list_custom_field_items(client, args):
    """List items for a hierarchy/weighted_item_list custom field."""
    items = await client.get_collection(
        f"/custom_fields/{args['custom_field_id']}/items"
    )
    if not items:
        return f"No items found for custom field #{args['custom_field_id']}."
    text = f"**Custom Field #{args['custom_field_id']} Items ({len(items)}):**\n\n"
    for item in items:
        text += f"- **{item.get('value', '?')}** (ID: {item.get('id')})\n"
    return text


# ── A7: Schema Introspection handlers (integration tool) ─────────────


async def h_int_get_work_package_schema(client, args):
    """Get the work package schema for a project/type combination."""
    if "project_id" not in args or "type_id" not in args:
        return "Both `project_id` and `type_id` are required. Use `project.list_types` to find valid type IDs for a project."
    pid = args["project_id"]
    tid = args["type_id"]
    r = await client.get(f"/work_packages/schemas/{pid}-{tid}")
    # Extract field names and their types for a useful summary
    text = f"**WP Schema (Project #{pid}, Type #{tid}):**\n\n"
    for field_name, field_def in r.items():
        if field_name.startswith("_") or not isinstance(field_def, dict):
            continue
        f_type = field_def.get("type", "?")
        required = field_def.get("required", False)
        writable = field_def.get("writable", True)
        name = field_def.get("name", field_name)
        text += f"- **{name}** ({field_name}): type={f_type}"
        if required:
            text += " [required]"
        if not writable:
            text += " [read-only]"
        # Show allowed values if present
        allowed = field_def.get("_links", {}).get("allowedValues")
        if allowed and isinstance(allowed, list) and len(allowed) <= 10:
            vals = ", ".join(
                a.get("title", a.get("value", "?")) for a in allowed
            )
            text += f" allowed=[{vals}]"
        text += "\n"
    return text


async def h_int_post_work_package_form(client, args):
    """Validate a draft WP payload via the form endpoint."""
    payload = args.get("payload", {})
    r = await client.post("/work_packages/form", payload)
    # Form response has _type, payload, schema, validationErrors
    errors = r.get("_embedded", {}).get("validationErrors", {})
    schema = r.get("_embedded", {}).get("schema", {})
    result_payload = r.get("_embedded", {}).get("payload", {})

    text = "**Work Package Form Validation:**\n\n"
    if errors:
        text += "**Validation Errors:**\n"
        for field, err in errors.items():
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            text += f"- {field}: {msg}\n"
    else:
        text += "No validation errors.\n"

    text += f"\n**Resolved Payload:**\n{json.dumps(result_payload, indent=2)[:2000]}\n"
    return text


# ── A8: View handlers (query_view tool) ──────────────────────────────


async def h_qv_list_views(client, args):
    """List all views (table, calendar, team planner, gantt)."""
    items = await client.get_collection("/views?pageSize=100")
    if not items:
        return "No views found."
    text = f"Found {len(items)} view(s):\n\n"
    for v in items:
        text += f"- **{v.get('_type', '?')}** (ID: {v.get('id')})\n"
    return text


async def h_qv_get_view(client, args):
    """Get a single view by ID."""
    r = await client.get(f"/views/{args['view_id']}")
    return (
        f"**View #{r.get('id')}:**\n"
        f"- Type: {r.get('_type', '?')}\n"
        f"{json.dumps(r, indent=2)[:2000]}\n"
    )


async def h_qv_create_view(client, args):
    """Create a new view of specified type."""
    view_type = args["view_type"]
    payload = args.get("payload", {})
    r = await client.post(f"/views/{view_type}", payload)
    return f"✅ View created: #{r.get('id')} (type: {r.get('_type', view_type)})"


# ═══════════════════════════════════════════════════════════════════════
# Operation Registry — maps (tool_name, operation) to handler function
# ═══════════════════════════════════════════════════════════════════════

REGISTRY = {
    # ── project (9 operations) ──
    ("project", "list"): h_project_list,
    ("project", "get"): h_project_get,
    ("project", "create"): h_project_create,
    ("project", "update"): h_project_update,
    ("project", "delete"): h_project_delete,
    ("project", "list_types"): h_project_list_types,
    ("project", "list_versions"): h_project_list_versions,
    ("project", "list_available_assignees"): h_project_list_available_assignees,
    ("project", "copy"): h_project_copy,
    ("project", "list_budgets"): h_project_list_budgets,
    ("project", "get_budget"): h_project_get_budget,
    # ── work_package (21 operations) ──
    ("work_package", "list"): h_wp_list,
    ("work_package", "get"): h_wp_get,
    ("work_package", "create"): h_wp_create,
    ("work_package", "update"): h_wp_update,
    ("work_package", "delete"): h_wp_delete,
    ("work_package", "set_parent"): h_wp_set_parent,
    ("work_package", "remove_parent"): h_wp_remove_parent,
    ("work_package", "list_children"): h_wp_list_children,
    ("work_package", "list_activities"): h_wp_list_activities,
    ("work_package", "add_comment"): h_wp_add_comment,
    ("work_package", "list_attachments"): h_wp_list_attachments,
    ("work_package", "list_watchers"): h_wp_list_watchers,
    ("work_package", "add_watcher"): h_wp_add_watcher,
    ("work_package", "remove_watcher"): h_wp_remove_watcher,
    ("work_package", "list_relations"): h_wp_list_relations,
    ("work_package", "create_relation"): h_wp_create_relation,
    ("work_package", "get_relation"): h_wp_get_relation,
    ("work_package", "update_relation"): h_wp_update_relation,
    ("work_package", "delete_relation"): h_wp_delete_relation,
    ("work_package", "list_available_watchers"): h_wp_list_available_watchers,
    ("work_package", "list_available_relation_candidates"): h_wp_list_available_relation_candidates,
    ("work_package", "add_attachment"): h_wp_add_attachment,
    ("work_package", "list_file_links"): h_wp_list_file_links,
    ("work_package", "add_file_links"): h_wp_add_file_links,
    # ── time_entry (6 operations) ──
    ("time_entry", "list"): h_te_list,
    ("time_entry", "get"): h_te_get,
    ("time_entry", "create"): h_te_create,
    ("time_entry", "update"): h_te_update,
    ("time_entry", "delete"): h_te_delete,
    ("time_entry", "list_activities"): h_te_list_activities,
    # ── membership (7 operations) ──
    ("membership", "list"): h_mem_list,
    ("membership", "get"): h_mem_get,
    ("membership", "create"): h_mem_create,
    ("membership", "update"): h_mem_update,
    ("membership", "delete"): h_mem_delete,
    ("membership", "list_project_members"): h_mem_list_project_members,
    ("membership", "list_user_projects"): h_mem_list_user_projects,
    # ── principal (15 operations) ──
    ("principal", "list_users"): h_principal_list_users,
    ("principal", "get_user"): h_principal_get_user,
    ("principal", "create_user"): h_principal_create_user,
    ("principal", "update_user"): h_principal_update_user,
    ("principal", "delete_user"): h_principal_delete_user,
    ("principal", "lock_user"): h_principal_lock_user,
    ("principal", "unlock_user"): h_principal_unlock_user,
    ("principal", "list_groups"): h_principal_list_groups,
    ("principal", "get_group"): h_principal_get_group,
    ("principal", "create_group"): h_principal_create_group,
    ("principal", "update_group"): h_principal_update_group,
    ("principal", "delete_group"): h_principal_delete_group,
    ("principal", "list_roles"): h_principal_list_roles,
    ("principal", "get_role"): h_principal_get_role,
    ("principal", "list_principals"): h_principal_list_principals,
    # ── version (6 operations) ──
    ("version", "list"): h_version_list,
    ("version", "get"): h_version_get,
    ("version", "create"): h_version_create,
    ("version", "update"): h_version_update,
    ("version", "delete"): h_version_delete,
    ("version", "list_projects"): h_version_list_projects,
    # ── query_view (8 operations) ──
    ("query_view", "list_queries"): h_qv_list_queries,
    ("query_view", "get_query"): h_qv_get_query,
    ("query_view", "create_query"): h_qv_create_query,
    ("query_view", "update_query"): h_qv_update_query,
    ("query_view", "delete_query"): h_qv_delete_query,
    ("query_view", "star_query"): h_qv_star,
    ("query_view", "unstar_query"): h_qv_unstar,
    ("query_view", "get_default_query"): h_qv_get_default,
    # ── notification (7 operations) ──
    ("notification", "list"): h_notif_list,
    ("notification", "get"): h_notif_get,
    ("notification", "get_detail"): h_notif_get_detail,
    ("notification", "mark_read"): h_notif_mark_read,
    ("notification", "mark_unread"): h_notif_mark_unread,
    ("notification", "mark_all_read"): h_notif_mark_all_read,
    ("notification", "mark_all_unread"): h_notif_mark_all_unread,
    # ── artifact (11 operations) ──
    ("artifact", "list_news"): h_art_list_news,
    ("artifact", "get_news"): h_art_get_news,
    ("artifact", "create_news"): h_art_create_news,
    ("artifact", "update_news"): h_art_update_news,
    ("artifact", "delete_news"): h_art_delete_news,
    ("artifact", "get_wiki_page"): h_art_get_wiki_page,
    ("artifact", "get_document"): h_art_get_document,
    ("artifact", "list_documents"): h_art_list_documents,
    ("artifact", "get_meeting"): h_art_get_meeting,
    ("artifact", "get_attachment"): h_art_get_attachment,
    ("artifact", "delete_attachment"): h_art_delete_attachment,
    ("artifact", "get_file_link"): h_art_get_file_link,
    ("artifact", "open_file_link"): h_art_open_file_link,
    ("artifact", "download_file_link"): h_art_download_file_link,
    ("artifact", "delete_file_link"): h_art_delete_file_link,
    # ── integration (14 operations) ──
    ("integration", "test_connection"): h_int_test_connection,
    ("integration", "check_permissions"): h_int_check_permissions,
    ("integration", "list_statuses"): h_int_list_statuses,
    ("integration", "get_status"): h_int_get_status,
    ("integration", "list_priorities"): h_int_list_priorities,
    ("integration", "get_priority"): h_int_get_priority,
    ("integration", "list_types"): h_int_list_types,
    ("integration", "get_type"): h_int_get_type,
    ("integration", "get_category"): h_int_get_category,
    ("integration", "list_categories"): h_int_list_categories,
    ("integration", "get_custom_action"): h_int_get_custom_action,
    ("integration", "execute_custom_action"): h_int_execute_custom_action,
    ("integration", "get_configuration"): h_int_get_configuration,
    ("integration", "render_markdown"): h_int_render_markdown,
    # A1: Day/Schedule operations
    ("integration", "list_days"): h_int_list_days,
    ("integration", "get_day"): h_int_get_day,
    ("integration", "list_non_working_days"): h_int_list_non_working_days,
    ("integration", "get_week_schedule"): h_int_get_week_schedule,
    # A6: Custom Field/Option operations
    ("integration", "get_custom_option"): h_int_get_custom_option,
    ("integration", "list_custom_field_items"): h_int_list_custom_field_items,
    # A7: Schema Introspection operations
    ("integration", "get_work_package_schema"): h_int_get_work_package_schema,
    ("integration", "post_work_package_form"): h_int_post_work_package_form,
    # A8: View operations
    ("query_view", "list_views"): h_qv_list_views,
    ("query_view", "get_view"): h_qv_get_view,
    ("query_view", "create_view"): h_qv_create_view,
}


# ═══════════════════════════════════════════════════════════════════════
# Tool Definitions — 10 parameterized tools
# ═══════════════════════════════════════════════════════════════════════

RELATION_TYPE_ENUM = [
    "blocks",
    "follows",
    "precedes",
    "relates",
    "duplicates",
    "includes",
    "requires",
    "partof",
]

TOOL_DEFINITIONS = [
    Tool(
        name="project",
        description="Manage projects: list, get, create, update, delete, list_types, list_versions, list_available_assignees, copy, list_budgets, get_budget",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "list_types",
                        "list_versions",
                        "list_available_assignees",
                        "copy",
                        "list_budgets",
                        "get_budget",
                    ],
                    "description": "Operation to perform",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (for get/update/delete/list_types/list_versions/list_available_assignees)",
                },
                "source_project_id": {
                    "type": "integer",
                    "description": "Source project ID (for copy)",
                },
                "name": {
                    "type": "string",
                    "description": "Project name (for create/update)",
                },
                "identifier": {
                    "type": "string",
                    "description": "Project identifier (for create/update)",
                },
                "description": {
                    "type": "string",
                    "description": "Project description",
                },
                "public": {
                    "type": "boolean",
                    "description": "Whether project is public",
                },
                "status": {
                    "type": "string",
                    "description": "Project status",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent project ID",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Show only active projects (for list)",
                    "default": True,
                },
                "payload": {
                    "type": "object",
                    "description": "Raw payload (for copy)",
                },
                "budget_id": {
                    "type": "integer",
                    "description": "Budget ID (for get_budget)",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="work_package",
        description=(
            "Manage work packages: list, get, create, update, delete, "
            "set_parent, remove_parent, list_children, list_activities, add_comment, "
            "list_attachments, add_attachment, list_watchers, add_watcher, remove_watcher, "
            "list_relations, create_relation, get_relation, update_relation, delete_relation, "
            "list_available_watchers, list_available_relation_candidates, "
            "list_file_links, add_file_links"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "set_parent",
                        "remove_parent",
                        "list_children",
                        "list_activities",
                        "add_comment",
                        "list_attachments",
                        "add_attachment",
                        "list_watchers",
                        "add_watcher",
                        "remove_watcher",
                        "list_relations",
                        "create_relation",
                        "get_relation",
                        "update_relation",
                        "delete_relation",
                        "list_available_watchers",
                        "list_available_relation_candidates",
                        "list_file_links",
                        "add_file_links",
                    ],
                    "description": "Operation to perform",
                },
                "work_package_id": {
                    "type": "integer",
                    "description": "Work package ID",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (for list/create)",
                },
                "subject": {
                    "type": "string",
                    "description": "Work package title (for create/update)",
                },
                "description": {
                    "type": "string",
                    "description": "Description (Markdown supported)",
                },
                "type_id": {
                    "type": "integer",
                    "description": "Type ID (for create/update)",
                },
                "status_id": {
                    "type": "integer",
                    "description": "Status ID (for update)",
                },
                "priority_id": {
                    "type": "integer",
                    "description": "Priority ID",
                },
                "assignee_id": {
                    "type": "integer",
                    "description": "Assignee user ID",
                },
                "percentage_done": {
                    "type": "integer",
                    "description": "Completion percentage 0-100",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date YYYY-MM-DD",
                },
                "date": {
                    "type": "string",
                    "description": "Date for milestones YYYY-MM-DD",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Status filter (for list)",
                    "default": "open",
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (for list)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size (for list, max 100)",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent WP ID (for set_parent/list_children)",
                },
                "include_descendants": {
                    "type": "boolean",
                    "description": "Include all descendants (for list_children)",
                    "default": False,
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID (for add_watcher/remove_watcher)",
                },
                "comment": {
                    "type": "string",
                    "description": "Comment text (for add_comment)",
                },
                "from_id": {
                    "type": "integer",
                    "description": "Source WP ID (for create_relation)",
                },
                "to_id": {
                    "type": "integer",
                    "description": "Target WP ID (for create_relation)",
                },
                "relation_type": {
                    "type": "string",
                    "enum": RELATION_TYPE_ENUM,
                    "description": "Relation type",
                },
                "relation_id": {
                    "type": "integer",
                    "description": "Relation ID (for get/update/delete_relation)",
                },
                "lag": {
                    "type": "integer",
                    "description": "Lag in working days (for relations)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for list_available_relation_candidates)",
                },
                "timestamps": {
                    "type": "string",
                    "description": "Comma-separated ISO-8601 timestamps or relative durations for baseline comparison (for list/get). Example: 'P-30D,PT0S'",
                },
                "file_name": {
                    "type": "string",
                    "description": "File name (for add_attachment)",
                },
                "content": {
                    "type": "string",
                    "description": "File content as string (for add_attachment)",
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME type (for add_attachment, default: application/octet-stream)",
                },
                "file_links": {
                    "type": "array",
                    "description": "Array of file link objects (for add_file_links, max 20)",
                    "items": {"type": "object"},
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="time_entry",
        description="Manage time entries: list, get, create, update, delete, list_activities",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "list_activities",
                    ],
                    "description": "Operation to perform",
                },
                "time_entry_id": {
                    "type": "integer",
                    "description": "Time entry ID (for get/update/delete)",
                },
                "work_package_id": {
                    "type": "integer",
                    "description": "Work package ID (for list filter/create)",
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID (for list filter)",
                },
                "hours": {
                    "type": "number",
                    "description": "Hours spent e.g. 2.5 (for create/update)",
                },
                "spent_on": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD (for create/update)",
                },
                "comment": {
                    "type": "string",
                    "description": "Comment (for create/update)",
                },
                "activity_id": {
                    "type": "integer",
                    "description": "Activity ID (for create/update)",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="membership",
        description="Manage memberships: list, get, create, update, delete, list_project_members, list_user_projects",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "list_project_members",
                        "list_user_projects",
                    ],
                    "description": "Operation to perform",
                },
                "membership_id": {
                    "type": "integer",
                    "description": "Membership ID (for get/update/delete)",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (for list/create/list_project_members)",
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID (for list/create/list_user_projects)",
                },
                "group_id": {
                    "type": "integer",
                    "description": "Group ID (for create, alternative to user_id)",
                },
                "role_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Role IDs (for create/update)",
                },
                "role_id": {
                    "type": "integer",
                    "description": "Single role ID (for create/update)",
                },
                "notification_message": {
                    "type": "string",
                    "description": "Notification message",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="principal",
        description=(
            "Manage users, groups, roles: list_users, get_user, create_user, "
            "update_user, delete_user, lock_user, unlock_user, list_groups, get_group, "
            "create_group, update_group, delete_group, list_roles, get_role, list_principals"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list_users",
                        "get_user",
                        "create_user",
                        "update_user",
                        "delete_user",
                        "lock_user",
                        "unlock_user",
                        "list_groups",
                        "get_group",
                        "create_group",
                        "update_group",
                        "delete_group",
                        "list_roles",
                        "get_role",
                        "list_principals",
                    ],
                    "description": "Operation to perform",
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID",
                },
                "group_id": {
                    "type": "integer",
                    "description": "Group ID",
                },
                "role_id": {
                    "type": "integer",
                    "description": "Role ID",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Show only active users (for list_users)",
                    "default": True,
                },
                "payload": {
                    "type": "object",
                    "description": "Raw payload (for create/update user/group)",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="version",
        description="Manage versions/milestones: list, get, create, update, delete, list_projects",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "list_projects",
                    ],
                    "description": "Operation to perform",
                },
                "version_id": {
                    "type": "integer",
                    "description": "Version ID (for get/update/delete/list_projects)",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (for list/create)",
                },
                "name": {
                    "type": "string",
                    "description": "Version name (for create/update)",
                },
                "description": {
                    "type": "string",
                    "description": "Version description",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD",
                },
                "status": {
                    "type": "string",
                    "description": "Version status (open/locked/closed)",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="query_view",
        description=(
            "Manage saved queries and views: list_queries, get_query, create_query, "
            "update_query, delete_query, star_query, unstar_query, get_default_query, "
            "list_views, get_view, create_view"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list_queries",
                        "get_query",
                        "create_query",
                        "update_query",
                        "delete_query",
                        "star_query",
                        "unstar_query",
                        "get_default_query",
                        "list_views",
                        "get_view",
                        "create_view",
                    ],
                    "description": "Operation to perform",
                },
                "query_id": {
                    "type": "integer",
                    "description": "Query ID",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (for get_default_query)",
                },
                "payload": {
                    "type": "object",
                    "description": "Query/view payload (for create/update)",
                },
                "view_id": {
                    "type": "integer",
                    "description": "View ID (for get_view)",
                },
                "view_type": {
                    "type": "string",
                    "enum": [
                        "work_packages_table",
                        "team_planner",
                        "work_packages_calendar",
                        "gantt",
                    ],
                    "description": "View type (for create_view)",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="notification",
        description="Manage notifications: list, get, get_detail, mark_read, mark_unread, mark_all_read, mark_all_unread",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "get_detail",
                        "mark_read",
                        "mark_unread",
                        "mark_all_read",
                        "mark_all_unread",
                    ],
                    "description": "Operation to perform",
                },
                "notification_id": {
                    "type": "integer",
                    "description": "Notification ID",
                },
                "detail_id": {
                    "type": "integer",
                    "description": "Detail ID (for get_detail)",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="artifact",
        description=(
            "Manage news, wiki pages, documents, meetings, attachments, file links: "
            "list_news, get_news, create_news, update_news, delete_news, "
            "get_wiki_page, get_document, list_documents, get_meeting, "
            "get_attachment, delete_attachment, "
            "get_file_link, open_file_link, download_file_link, delete_file_link"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list_news",
                        "get_news",
                        "create_news",
                        "update_news",
                        "delete_news",
                        "get_wiki_page",
                        "get_document",
                        "list_documents",
                        "get_meeting",
                        "get_attachment",
                        "delete_attachment",
                        "get_file_link",
                        "open_file_link",
                        "download_file_link",
                        "delete_file_link",
                    ],
                    "description": "Operation to perform",
                },
                "news_id": {
                    "type": "integer",
                    "description": "News ID",
                },
                "wiki_page_id": {
                    "type": "integer",
                    "description": "Wiki page ID",
                },
                "document_id": {
                    "type": "integer",
                    "description": "Document ID",
                },
                "meeting_id": {
                    "type": "integer",
                    "description": "Meeting ID",
                },
                "attachment_id": {
                    "type": "integer",
                    "description": "Attachment ID",
                },
                "file_link_id": {
                    "type": "integer",
                    "description": "File link ID (for get/open/download/delete_file_link)",
                },
                "payload": {
                    "type": "object",
                    "description": "Payload for create/update",
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="integration",
        description=(
            "Platform integration: test_connection, check_permissions, "
            "list_statuses, get_status, list_priorities, get_priority, "
            "list_types, get_type, get_category, list_categories, "
            "get_custom_action, execute_custom_action, get_configuration, render_markdown, "
            "list_days, get_day, list_non_working_days, get_week_schedule, "
            "get_custom_option, list_custom_field_items, "
            "get_work_package_schema, post_work_package_form"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "test_connection",
                        "check_permissions",
                        "list_statuses",
                        "get_status",
                        "list_priorities",
                        "get_priority",
                        "list_types",
                        "get_type",
                        "get_category",
                        "list_categories",
                        "get_custom_action",
                        "execute_custom_action",
                        "get_configuration",
                        "render_markdown",
                        "list_days",
                        "get_day",
                        "list_non_working_days",
                        "get_week_schedule",
                        "get_custom_option",
                        "list_custom_field_items",
                        "get_work_package_schema",
                        "post_work_package_form",
                    ],
                    "description": "Operation to perform",
                },
                "status_id": {
                    "type": "integer",
                    "description": "Status ID",
                },
                "priority_id": {
                    "type": "integer",
                    "description": "Priority ID",
                },
                "type_id": {
                    "type": "integer",
                    "description": "Type ID",
                },
                "category_id": {
                    "type": "integer",
                    "description": "Category ID",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (for list_categories/list_types)",
                },
                "custom_action_id": {
                    "type": "integer",
                    "description": "Custom action ID",
                },
                "work_package_id": {
                    "type": "integer",
                    "description": "Work package ID (for execute_custom_action)",
                },
                "lock_version": {
                    "type": "integer",
                    "description": "Lock version (for execute_custom_action)",
                },
                "text": {
                    "type": "string",
                    "description": "Markdown text (for render_markdown)",
                },
                "date": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD (for get_day)",
                },
                "from_date": {
                    "type": "string",
                    "description": "Start date filter YYYY-MM-DD (for list_days/list_non_working_days)",
                },
                "to_date": {
                    "type": "string",
                    "description": "End date filter YYYY-MM-DD (for list_days/list_non_working_days)",
                },
                "working": {
                    "type": "boolean",
                    "description": "Filter by working/non-working status (for list_days)",
                },
                "custom_option_id": {
                    "type": "integer",
                    "description": "Custom option ID (for get_custom_option)",
                },
                "custom_field_id": {
                    "type": "integer",
                    "description": "Custom field ID (for list_custom_field_items)",
                },
                "payload": {
                    "type": "object",
                    "description": "Draft WP payload (for post_work_package_form)",
                },
            },
            "required": ["operation"],
        },
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# MCP Server
# ═══════════════════════════════════════════════════════════════════════


class OpenProjectMCPServer:
    """MCP Server for OpenProject — 10 consolidated tools, 122 operations."""

    def __init__(self):
        self.server = Server("openproject-mcp")
        self.client: Optional[OpenProjectClient] = None
        self._setup_handlers()

    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return TOOL_DEFINITIONS

        @self.server.call_tool()
        async def call_tool(
            name: str, arguments: Dict[str, Any]
        ) -> List[TextContent]:
            if not self.client:
                return [
                    TextContent(
                        type="text",
                        text=(
                            "Error: OpenProject Client not initialized. "
                            "Set OPENPROJECT_URL and OPENPROJECT_API_KEY."
                        ),
                    )
                ]

            operation = arguments.get("operation")
            if not operation:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Missing 'operation' parameter for tool '{name}'.",
                    )
                ]

            handler = REGISTRY.get((name, operation))
            if not handler:
                ops = sorted(
                    op for (t, op) in REGISTRY if t == name
                )
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"❌ Unknown operation '{operation}' for tool '{name}'.\n"
                            f"Available: {', '.join(ops)}"
                        ),
                    )
                ]

            try:
                result_text = await handler(self.client, arguments)
                return [TextContent(type="text", text=result_text)]
            except Exception as e:
                logger.error(
                    f"Error in {name}.{operation}: {e}", exc_info=True
                )
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Error in {name}.{operation}: {str(e)}",
                    )
                ]

    async def run(self):
        """Start the MCP server."""
        base_url = os.getenv("OPENPROJECT_URL")
        api_key = os.getenv("OPENPROJECT_API_KEY")
        proxy = os.getenv("OPENPROJECT_PROXY")

        if not base_url or not api_key:
            logger.error("OPENPROJECT_URL or OPENPROJECT_API_KEY not set!")
            logger.info(
                "Please set the required environment variables in .env file"
            )
        else:
            self.client = OpenProjectClient(base_url, api_key, proxy)
            logger.info(f"✅ OpenProject Client initialized for {base_url}")

            if (
                os.getenv("TEST_CONNECTION_ON_STARTUP", "false").lower()
                == "true"
            ):
                try:
                    await self.client.get("")
                    logger.info("✅ API connection test successful!")
                except Exception as e:
                    logger.error(f"❌ API connection test failed: {e}")

        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


async def main():
    """Main entry point."""
    logger.info(f"Starting OpenProject MCP Server v{__version__}")
    server = OpenProjectMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
