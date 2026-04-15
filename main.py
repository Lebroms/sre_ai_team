import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

# Load environment variables
load_dotenv()

# ==========================================
# 1. AI MODEL SETUP
# ==========================================
# Primary provider: Gemini (with manual fallback to Groq)
gemini_llm =LLM(                     # Replace with gemini-3.1-flash-lite, gemini-2.5-flash, gemini-1.5-flash if you prefer
    model="gemini/gemini-2.5-flash", # LiteLLM syntax: provider/model-name
    api_key=os.environ.get("GEMINI_API_KEY"),
    temperature=0.1 # Low temperature for analytical and deterministic SRE reasoning
)

sre_llm_engine = gemini_llm


# ==========================================
# 2. DATA CONTRACT DEFINITION (The JSON captured by n8n)
# ==========================================
alert_payload = """
{
  "alertname": "PodCrashLooping",
  "namespace": "cloudops-shoes",
  "pod": "chaos-crashloop",
  "reason": "CrashLoopBackOff",
  "severity": "critical",
  "description": "The pod has been crashing repeatedly for over 1 minute."
}
"""

# ==========================================
# 3, 4, 5. CREW CONSTRUCTION (encapsulated to support fallback)
# ==========================================
def create_sre_crew(llm_engine):
    investigatore_sre = Agent(
        role='Senior SRE Incident Responder',
        goal='Analyze Kubernetes alerts and draft a clear and technical initial investigation plan.',
        backstory=(
            "You are a veteran SRE engineer. When you receive an alert about a crashing pod, "
            "you do not panic. You analyze the available data, identify the namespace and the pod, "
            "and prepare a list of kubectl commands that a junior engineer should run to understand the problem. "
            "You are direct, precise, and use technical language appropriate for a Cloud Native environment."
        ),
        llm=llm_engine, # <-- Injection of the provided High-Reliability engine
        verbose=True,
        allow_delegation=False
    )

    analisi_iniziale_task = Task(
        description=(
            f"The following alert has just fired from Prometheus/Alertmanager:\n\n"
            f"{alert_payload}\n\n"
            f"Your task is:\n"
            f"1. Extract the critical details of the alert.\n"
            f"2. Briefly explain what the reported status means in a Kubernetes context.\n"
            f"3. Write the 3 exact 'kubectl' commands you would run to troubleshoot this specific pod in its namespace."
        ),
        expected_output="A Markdown report with the alert analysis and the kubectl commands ready to run.",
        agent=investigatore_sre
    )

    return Crew(
        agents=[investigatore_sre],
        tasks=[analisi_iniziale_task],
        process=Process.sequential
    )

# Initial Crew creation with the primary engine
sre_crew = create_sre_crew(sre_llm_engine)

if __name__ == "__main__":
    print("🚀 Starting AIOps investigation...")
    print("🧠 Engine: Gemini (with fallback to Groq Llama-3)")
    print("----------------------------------------------\n")
    
    try:
        risultato = sre_crew.kickoff()
    except Exception as e:
        print(f"\n⚠️ Gemini API exception: {e}")
        print("🔄 Error detected. Activating manual fallback to Groq...")
        
        # We use CrewAI's native LLM with Groq's OpenAI-compatible endpoint.
        # WARNING: We intentionally omit the "openai/" prefix in model= to avoid
        # CrewAI invoking LiteLLM (which is not installed in the user's venv).
        groq_llm = LLM(
            model="llama-3.3-70b-versatile",
            api_key=os.environ.get("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            temperature=0.1
        )
        
        # We update the crew by rebuilding it from scratch with the new LLM 
        # to clear CrewAI's internal caches!
        sre_crew_fallback = create_sre_crew(groq_llm)
        
        # We rerun the execution
        risultato = sre_crew_fallback.kickoff()
    
    print("\n==============================================")
    print("📋 SRE AGENT REPORT:")
    print("==============================================")
    print(risultato)



'''

# Import the classes for model High Availability
from langchain_openai import ChatOpenAI
# from langchain_groq import ChatGroq

# ==========================================
# 1. AI MODEL SETUP (HA / Fallback architecture)
# ==========================================
# Primary provider: Gemini through an OpenAI-compatible endpoint
gemini_llm = ChatOpenAI(
    api_key=os.environ.get("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-2.5-flash", # Replace with gemini-3.1-flash-lite if you prefer
    temperature=0.1 # Low temperature for analytical and deterministic SRE reasoning
)

# Fallback provider: Llama-3 on Groq
groq_llm = ChatGroq(
    api_key=os.environ.get("GROQ_API_KEY"),
    model_name="llama3-70b-8192",
    temperature=0.1
)

# Creation of the reliability chain: if Gemini fails, Groq takes over
#sre_llm_engine = gemini_llm.with_fallbacks([groq_llm])
# 
# 
# Primary provider: Gemini
gemini_llm = LLM(
    api_key=os.environ.get("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-2.5-flash", # Replace with gemini-3.1-flash-lite if you prefer
    provider="gemini",
    temperature=0.1 # Low temperature for analytical and deterministic SRE reasoning
)

sre_llm_engine = gemini_llm'''
