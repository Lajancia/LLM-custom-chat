from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import asyncio
import json
import re
import subprocess
from datetime import date
from pathlib import Path
from dolphin_mcp import run_interaction
import os
from dotenv import load_dotenv
load_dotenv()

DEFAULT_LOCATION = "Seoul, South Korea"

# —————————————————————————————————————————————————————————————
# 2) Load your MCP servers config
CONFIG_PATH = Path("mcp_config.json")
MCP_CFG = json.loads(CONFIG_PATH.read_text())["mcpServers"]
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PARENT_PAGE_ID= os.getenv("NOTION_PARENT_PAGE_ID")
# Ollama 설정
OLLAMA_URL = "http://host.docker.internal:11434/api/generate"
OLLAMA_MODEL = "llama3"

# In-memory chat history (for current process only)
CHAT_HISTORY = []

async def call_tool(tool_call: dict) -> str:
    name = tool_call["name"]
    server_key = name.split("-", 1)[0]
    cfg = MCP_CFG.get(server_key)
    if not cfg:
        return f"[Error] No MCP server for '{server_key}'"

    # .env에서 읽은 환경변수와 기존 cfg.get("env", {})를 합침
    merged_env = {**os.environ, **cfg.get("env", {})}

    cmd = [cfg["command"], *cfg.get("args", [])]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env
    )

    payload = json.dumps(tool_call) + "\n"
    out, err = proc.communicate(payload)

    # If error, check for missing parent/page_id and retry ONCE
    if err and ("parent" in err.lower() or "page_id" in err.lower()):
        print("🔄 Retrying with fixed parent.page_id...")
        parent_page_id = NOTION_PARENT_PAGE_ID
        # Fix the arguments
        if "arguments" in tool_call:
            args = tool_call["arguments"]
            if "parent" not in args or not args["parent"]:
                args["parent"] = {"page_id": parent_page_id}
            elif "page_id" not in args["parent"]:
                args["parent"]["page_id"] = parent_page_id
            # Fix for Notion MCP: parse stringified lists
            if "properties" in args and "title" in args["properties"]:
                if isinstance(args["properties"]["title"], str):
                    try:
                        args["properties"]["title"] = json.loads(args["properties"]["title"])
                    except Exception:
                        pass
            # Fix children
            if "children" in args and isinstance(args["children"], str):
                try:
                    args["children"] = json.loads(args["children"])
                except Exception:
                    pass
            tool_call["arguments"] = args
        # Retry
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        payload = json.dumps(tool_call) + "\n"
        out, err = proc.communicate(payload)

    if err:
        return f"[Tool Error] {err.strip()}"

    try:
        resp = json.loads(out)
        return resp.get("content") or resp.get("results") or out.strip()
    except json.JSONDecodeError:
        return out.strip()

# --- Single-turn chat logic for API ---
async def chat_once(user_input):
    today = date.today().isoformat()
    system_preface = (
        f"[System] Today's date is {today}. Your default location is {DEFAULT_LOCATION}. "
        "You're name is Neo"
        "If use ask with korean, answer in korean."
        "Whenever I ask about the weather, you can assume that's my location."
        "Whenever I ask questions related to today's date, you can assume it's today's date is {today}."
        "Whenever I ask in Korean, you should translate it into English and answer in Korean."
        f"""
        the parent parameter is 1ecdeb8e405c801abe9ff1735550e9ae. you must use this if you need it.
        if you receive a request to create a Notion page, the query should be in the following format:
        {{"parent": {{"page_id": "1ecdeb8e405c801abe9ff1735550e9ae"}}, "properties": {{"title": [{{"text": {{"content": "제목"}}}}]}}, "children": [{{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [{{"type": "text", "text": {{"content": "내용"}}}}]}}}}]}}

        example: {{"parent": {{"page_id": "1ecdeb8e405c801abe9ff1735550e9ae"}}, "properties": {{"title": [{{"text": {{"content": "2027년 7월 6일"}}}}]}}, "children": [{{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [{{"type": "text", "text": {{"content": "MCP (Model Context Protocol)는 AI 모델과 외부 도구 간의 표준화된 통신 프로토콜입니다..."}}}}]}}}}]}}
        Use this format to create a Notion page when tool_call.
        """
    )
    combined_query = system_preface + "\n\n" + user_input + "translate in to English"
    raw = await run_interaction(
        user_query=combined_query,
        model_name="llama3.1:8b",
        config_path=str(CONFIG_PATH),
        quiet_mode=False
    )
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return raw or ""
    # Handle chained tool calls (single chain)
    if isinstance(result, dict) and result.get("tool_call"):
        tc = result["tool_call"]
        tool_out = await call_tool(tc)
        # Feed the tool result back to Llama
        raw = await run_interaction(
            user_query=f"Tool result: {tool_out}",
            model_name="llama3.1:8b",
            config_path=str(CONFIG_PATH),
            quiet_mode=False,
        )
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            result = raw
    final = result.get("response") if isinstance(result, dict) else result
    return final or ""

@csrf_exempt    
@require_http_methods(["POST"])
def chat_api(request):
    """채팅 API 엔드포인트"""
    try:
        data = json.loads(request.body)
        user_input = data.get('message', '')
        print("user_input", user_input)
        ai_response = asyncio.run(chat_once(user_input))
        # Save to in-memory chat history
        CHAT_HISTORY.insert(0, {
            'user_input': user_input,
            'ai_response': ai_response,
            'timestamp': date.today().isoformat()
        })
        del CHAT_HISTORY[50:]
        return JsonResponse({'response': ai_response})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def chat_history(request):
    """대화 기록 조회"""
    return JsonResponse({'conversations': CHAT_HISTORY[:50]})

def home(request):
    """홈페이지"""
    return render(request, 'assistant/home.html')
