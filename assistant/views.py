from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import asyncio
import json
import subprocess
from datetime import date
from pathlib import Path
from dolphin_mcp import run_interaction
import os
from dotenv import load_dotenv
import requests
from langdetect import detect

load_dotenv()

DEFAULT_LOCATION = "Seoul, South Korea"

# —————————————————————————————————————————————————————————————
# 2) Load your MCP servers config
CONFIG_PATH = Path("mcp_config.json")
MCP_CFG = json.loads(CONFIG_PATH.read_text())["mcpServers"]
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PARENT_PAGE_ID= os.getenv("NOTION_PARENT_PAGE_ID")
# Ollama 설정
OLLAMA_URL = "http://localhost:11434/api/generate"
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
        "Whenever I ask about the weather, you can assume that's my location."
        "Whenever I ask questions related to today's date, you can assume it's today's date is {today}."

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
    # Handle multiple tool calls
    if isinstance(result, dict) and result.get("tool_call"):
        tool_calls = result["tool_call"]
        if isinstance(tool_calls, list):
            tool_results = []
            for tc in tool_calls:
                tool_out = await call_tool(tc)
                tool_results.append(tool_out)
            # Feed all tool results back to Llama
            tool_results_text = "\n".join(f"Tool result {i+1}: {r}" for i, r in enumerate(tool_results))
            raw = await run_interaction(
                user_query=tool_results_text,
                model_name="llama3.1:8b",
                config_path=str(CONFIG_PATH),
                quiet_mode=False,
            )
            try:
                result = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                result = raw
        else:
            tc = tool_calls
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

def ollama_translate(text, target_lang):
    """
    Use Ollama to translate text to the target language ('en' or 'ko').
    """
    if not text or not text.strip():
        print("[DEBUG] No text to translate.")
        return ""
    # 텍스트 전처리
    text = text.strip().strip('\"').replace('\\n', '\n')
    if target_lang == 'en':
        prompt = f"Please translate the following content into English:\n\n{text}\n\nEnglish:"
    else:
        prompt = f"다음 영어 문장을 자연스러운 한국어로 번역해 주세요:\n\n{text}\n\n번역:"
    data = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    try:
        response = requests.post(OLLAMA_URL, json=data)
        response.raise_for_status()
        return response.json().get("response", "")
    except Exception as e:
        return f"[Translation Error] {e}"

# Ollama LLM 직접 호출 함수
NEO_PROMPT = (
    "너의 이름은 Neo야."
)
def ask_ollama(prompt, model=OLLAMA_MODEL):
    full_prompt = f"{NEO_PROMPT}\n\n사용자: {prompt}\nNeo:"
    data = {"model": model, "prompt": full_prompt, "stream": False}
    try:
        response = requests.post(OLLAMA_URL, json=data)
        response.raise_for_status()
        return response.json().get("response", "답변을 가져오지 못했습니다.")
    except Exception as e:
        return f"Ollama와 통신 중 오류 발생: {e}"

# 정보성 질문 키워드 기반 분류
INFO_KEYWORDS = ["날씨", "주식", "증시", "검색", "뉴스", "환율", "ETF", "코스피", "코스닥", "S&P", "QQQ", "VOO"]
def is_info_query(user_input):
    return any(keyword in user_input for keyword in INFO_KEYWORDS)

@csrf_exempt    
@require_http_methods(["POST"])
def chat_api(request):
    """채팅 API 엔드포인트"""
    try:
        data = json.loads(request.body)
        user_input = data.get('message', '')
        print("user_input", user_input)
        # Always translate input to English
        user_input_en = ollama_translate(user_input, 'en')
        print(f"[DEBUG] Translated input to English: {user_input_en}")
        if is_info_query(user_input):
            # 정보성 질문: MCP tool_call 활용
            ai_response = asyncio.run(chat_once(user_input_en))
        else:
            # 일반 대화: Ollama LLM만 사용
            ai_response = ask_ollama(user_input_en)
        print(f"[DEBUG] AI response (English): {ai_response!r}")
        if not ai_response or not str(ai_response).strip():
            ai_response = "[오류] AI가 답변을 생성하지 못했습니다."
        # Always translate response to Korean
        ai_response_ko = ollama_translate(ai_response, 'ko')
        print(f"[DEBUG] Translated response to Korean: {ai_response_ko}")
        # Remove 'Here is the translation:' and similar phrases
        for prefix in [
            "Here is the translation:", "Here is the translation of the text to Korean:",
            "다음은 번역입니다:", "아래는 번역입니다:", "Here is your translation:", "번역:"
        ]:
            if ai_response_ko.strip().startswith(prefix):
                ai_response_ko = ai_response_ko.strip()[len(prefix):].lstrip()
        # Save to in-memory chat history
        CHAT_HISTORY.insert(0, {
            'user_input': user_input,
            'ai_response': ai_response_ko,
            'timestamp': date.today().isoformat()
        })
        del CHAT_HISTORY[50:]
        return JsonResponse({'response': ai_response_ko})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def chat_history(request):
    """대화 기록 조회"""
    return JsonResponse({'conversations': CHAT_HISTORY[:50]})

def home(request):
    """홈페이지"""
    return render(request, 'assistant/home.html')
