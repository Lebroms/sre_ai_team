from crewai import Agent, Task, Crew, Process, LLM

# ==========================================
# 1. LOCAL AI MODEL SETUP (Ollama)
# ==========================================
# Pointing the LLM class to the local Ollama instance running on port 11434.
local_llm = LLM(
    model="ollama/qwen2.5-coder:7b",
    base_url="http://localhost:11434",
    temperature=0.1 # Keep it low for precise SRE troubleshooting
)

# ==========================================
# 2. DATA CONTRACT DEFINITION (The JSON)
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
# 3. Agents (Your Local Team)
# ==========================================
investigatore_sre = Agent(
    role='Senior SRE Incident Responder',
    goal='Analyze Kubernetes alerts and draft a clear and technical initial investigation plan.',
    backstory=(
        "You are a veteran SRE engineer. When you receive an alert about a crashing pod, "
        "you do not panic. You analyze the available data, identify the namespace and the pod, "
        "and prepare a list of kubectl commands that a junior engineer should run to understand the problem. "
        "You are direct, precise, and use technical language appropriate for a Cloud Native environment."
    ),
    llm=local_llm, # Inject the local Qwen model
    verbose=True,
    allow_delegation=False
)

# ==========================================
# 4. Tasks (The Work Tickets)
# ==========================================
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

# ==========================================
# 5. The Crew (Execution)
# ==========================================
sre_crew = Crew(
    agents=[investigatore_sre],
    tasks=[analisi_iniziale_task],
    process=Process.sequential
)

if __name__ == "__main__":
    print("🚀 Starting LOCAL AIOps investigation...")
    print("🧠 Engine: Qwen 2.5 Coder 7B (via Ollama)")
    print("----------------------------------------------\n")
    
    risultato = sre_crew.kickoff()
    
    print("\n==============================================")
    print("📋 SRE AGENT REPORT (LOCAL):")
    print("==============================================")
    print(risultato)