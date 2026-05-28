"""FastAPI capabilities endpoint for picobot frontend bootstrapping."""

from __future__ import annotations

import importlib.util

from fastapi import APIRouter, Request

from simplified_chatbot.server.common import get_runtime
from simplified_chatbot.server.schemas import (
    CapabilitiesFeatures,
    CapabilitiesModelInfo,
    CapabilitiesResponse,
    CapabilitiesToolInfo,
)
from simplified_chatbot.tools.registry import ToolRegistry

router = APIRouter()

_SHELL_TOOLS = frozenset({"exec"})
_FILESYSTEM_TOOLS = frozenset(
    {"read_file", "write_file", "edit_file", "list_dir", "glob", "grep"},
)
_DANGEROUS_TOOLS = frozenset({"exec", "write_file", "edit_file"})

# Central zh display names + concise descriptions for built-in tools.
# MCP tools fall through to the per-Tool `display_name` / `description_zh`
# properties (if defined), then to the raw English name.
_TOOL_ZH: dict[str, tuple[str, str]] = {
    # filesystem
    "read_file": ("讀取檔案", "讀取工作區內的檔案內容"),
    "write_file": ("寫入檔案", "建立或覆寫工作區檔案"),
    "edit_file": ("編輯檔案", "對檔案做字串替換式編輯"),
    "list_dir": ("列出資料夾", "列出資料夾內的檔案"),
    "glob": ("搜尋路徑", "用萬用字元搜尋檔案路徑"),
    "grep": ("搜尋內容", "在檔案內容中搜尋關鍵字"),
    "find_files": ("尋找檔案", "尋找工作區內的相關檔案"),
    "apply_patch": ("套用補丁", "根據 unified diff 格式的補丁修改檔案"),
    # shell
    "exec": ("執行指令", "在工作區內執行 shell 指令"),
    "write_stdin": ("寫入標準輸入", "用於與已啟動且持續執行的 exec 命令互動"),
    "list_exec_sessions": ("列出指令執行", "列出目前正在執行的 exec 命令"),
    # subagents
    "spawn": ("派發子代理", "建立並執行一個子代理任務"),
    "list_subagents": ("列出子代理", "查看目前的子代理列表"),
    "subagent_status": ("子代理狀態", "查詢單一子代理的執行狀態"),
    "subagent_wait": ("等待子代理", "等待子代理完成並取得結果"),
    "cancel_subagent": ("取消子代理", "取消正在執行的子代理"),
    # search / web
    "tavily_search": ("Tavily 搜尋", "用 Tavily 搜尋網路資訊"),
    # skills / docs
    "read_skill": ("讀取 skill", "讀取技能定義"),
    "read_pdf": ("讀取 PDF", "解析 PDF 檔案內容"),
    "read_docx": ("讀取 Word", "解析 .docx 檔案內容"),
    "read_xlsx": ("讀取 Excel", "解析 .xlsx 試算表內容"),
    # demo / fake
    "echo": ("回音", "回傳輸入內容（測試用）"),
    "get_weather": ("查詢天氣", "查詢城市天氣（範例工具）"),
    "calculator": ("計算機", "計算數學表達式（範例工具）"),
}


def _tool_zh_lookup(name: str, tool: object) -> tuple[str | None, str | None]:
    """Resolve zh display_name / description for one tool.

    Order: per-Tool property override → central map → None.
    """
    display = getattr(tool, "display_name", None)
    description_zh = getattr(tool, "description_zh", None)
    if isinstance(display, str) and display.strip():
        resolved_display: str | None = display
    else:
        resolved_display = None
    if isinstance(description_zh, str) and description_zh.strip():
        resolved_desc: str | None = description_zh
    else:
        resolved_desc = None
    if resolved_display is None or resolved_desc is None:
        mapped = _TOOL_ZH.get(name)
        if mapped is not None:
            if resolved_display is None:
                resolved_display = mapped[0]
            if resolved_desc is None:
                resolved_desc = mapped[1]
    return resolved_display, resolved_desc


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(request: Request) -> CapabilitiesResponse:
    """Return frontend-friendly runtime capabilities."""
    runtime = get_runtime(request)
    chatbot = runtime.chatbot
    config = getattr(chatbot, "config", None)
    tools = getattr(chatbot, "tools", None)

    provider_name = str(getattr(config, "provider", "unknown"))
    model_name = str(getattr(config, "model", "unknown"))
    available_models = getattr(config, "available_models", []) if config is not None else []
    max_iterations = int(getattr(config, "max_iterations", 0) or 0)
    default_temperature = float(getattr(config, "temperature", 0.7) or 0.7)
    default_max_tokens_raw = getattr(config, "max_tokens", None)
    default_max_tokens = int(default_max_tokens_raw) if default_max_tokens_raw else None
    default_system_prompt = str(getattr(chatbot, "system_prompt", "") or "")

    return CapabilitiesResponse(
        model=CapabilitiesModelInfo(
            provider=provider_name,
            name=model_name,
        ),
        available_models=[
            item
            for item in (available_models or [model_name])
            if isinstance(item, str) and item
        ],
        max_iterations=max_iterations,
        tools=_build_tool_capabilities(tools),
        default_system_prompt=default_system_prompt,
        default_temperature=default_temperature,
        default_max_tokens=default_max_tokens,
        features=CapabilitiesFeatures(
            streaming=True,
            session_workspace=runtime.workspace_manager is not None,
            file_upload=(
                runtime.workspace_manager is not None
                and importlib.util.find_spec("multipart") is not None
            ),
            multimodal=True,
            model_override=True,
        ),
    )


def _build_tool_capabilities(tools: object) -> list[CapabilitiesToolInfo]:
    if not isinstance(tools, ToolRegistry):
        return []

    items: list[CapabilitiesToolInfo] = []
    get_tool = getattr(tools, "get", None)
    for schema in tools.get_definitions():
        function = schema.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = function.get("description")
        tool_obj = get_tool(name) if callable(get_tool) else None
        display_name, description_zh = _tool_zh_lookup(name, tool_obj)
        items.append(
            CapabilitiesToolInfo(
                name=name,
                description=description if isinstance(description, str) else "",
                category=_tool_category(name),
                dangerous=name in _DANGEROUS_TOOLS,
                display_name=display_name,
                description_zh=description_zh,
            ),
        )
    return items


def _tool_category(name: str) -> str:
    if name in _SHELL_TOOLS:
        return "shell"
    if name in _FILESYSTEM_TOOLS:
        return "filesystem"
    if name.startswith("mcp_"):
        return "mcp"
    return "other"
