import os 
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from crewai import Agent, Task, Crew, Process, LLM
from crewai.mcp import MCPServerStdio


# ==========================================
# SETUP MCP SERVER (Kubernetes)
# ==========================================
# Copiamo le variabili d'ambiente di Windows in modo che "uvx" e "kubectl" funzionino
mcp_env = os.environ.copy()
# SOSTITUISCI CON IL PATH CORRETTO DI WINDOWS (usa i doppi slash per evitare escape di python)
mcp_env["KUBECONFIG"] = "C:\\Users\\emagi\\.kube\\config"

# Inizializziamo la connessione Stdio verso il server MCP ufficiale di K8s
kubernetes_mcp = MCPServerStdio(
    command="uvx",
    args=["kubernetes-mcp-server@latest"],
    env=mcp_env
)

# ==========================================
# SETUP MCP SERVER (GitHub Custom)
# ==========================================
# Avviamo il nostro script python come server MCP indipendente
github_mcp = MCPServerStdio(
    command=sys.executable, # Usa l'interprete Python corrente
    args=["github_mcp_server.py"], # Punta al file che abbiamo appena creato
    env=os.environ.copy() # Passa il token GitHub caricato da .env
)

# ==========================================
# 1. INIZIALIZZAZIONE FASTAPI E CONFIGURAZIONE
# ==========================================
app = FastAPI(
    title="AIOps SRE Brain API",
    description="Microservizio AI per l'analisi Zero-Touch degli allarmi K3s e remediation GitOps",
    version="1.0.0"
)

'''# Setup LLM Locale (Ollama)
# Nota: La GPU NVIDIA GTX 1660 Ti gestirà l'inferenza localmente
local_llm = LLM(
    model="ollama/qwen2.5-coder:7b",
    base_url="http://localhost:11434",
    temperature=0.1 # Temperatura bassa per risposte tecniche e deterministiche
)'''

'''# ==========================================
# TRUCCO SRE: FORZARE IL TOOL CALLING (OPENAI EMULATION)
# ==========================================
# LiteLLM (usato da CrewAI) richiede una chiave fittizia per i provider OpenAI-compatibili
os.environ["OPENAI_API_KEY"] = "ollama-local"

local_llm = LLM(
    # Cambiamo il prefisso da "ollama/" a "openai/"
    model="openai/qwen2.5-coder:7b",
    # Puntiamo all'endpoint /v1 di Ollama che gestisce il function calling standard
    base_url="http://localhost:11434/v1",
    temperature=0.1
)'''

local_llm = LLM(
    model="openai/gpt-4.1-mini",  # o "openai/gpt-4.1-mini" se più stabile
    base_url=os.getenv("OPENAI_BASE_URL"),
    temperature=0.1  # bassa temperatura per comandi infrastrutturali deterministici
)
# ==========================================
# 2. DATA CONTRACT DEFINITION (PYDANTIC)
# ==========================================
# Questa classe definisce e valida il payload in ingresso da n8n
class AlertPayload(BaseModel):
    alertname: str
    namespace: str
    pod: str
    reason: str
    severity: str
    description: str

# ==========================================
# 3. ENDPOINT REST
# ==========================================
@app.post("/api/v1/alerts/analyze")
def analyze_alert(alert: AlertPayload):
    """
    Riceve un webhook da n8n/Alertmanager, inietta i dati nella CrewAI 
    e restituisce un report Markdown di investigazione iniziale.
    """
    print(f"🚀 [AIOps] Ricevuto allarme {alert.severity.upper()}: {alert.alertname} sul pod '{alert.pod}'")

    # Estrazione e formattazione dinamica del payload per il prompt dell'agente
    alert_context = (
        f"Alert Name: {alert.alertname}\n"
        f"Namespace: {alert.namespace}\n"
        f"Pod: {alert.pod}\n"
        f"Reason: {alert.reason}\n"
        f"Severity: {alert.severity}\n"
        f"Description: {alert.description}"
    )

    # ==========================================
    # DEFINIZIONE Architettura Multi-Agente
    # ==========================================

    def k8s_action_callback(step_output):
        """
        Intercetta le azioni dell'agente controllando esplicitamente la classe dell'oggetto.
        Fornisce un Audit Trail pulito per gli strumenti MCP.
        """
        print("\n" + "="*60)
        print("🕵️  [AUDIT TRAIL - ESECUZIONE SRE]")
        
        try:
            # CrewAI a volte passa una lista, a volte un singolo oggetto
            steps = step_output if isinstance(step_output, list) else [step_output]
            
            for step in steps:
                # Se CrewAI incapsula l'azione in una tupla (Azione, Risultato), prendiamo l'Azione
                action = step[0] if isinstance(step, tuple) else step
                
                # Identifichiamo il tipo di oggetto in modo esatto
                class_name = type(action).__name__
                
                if class_name == 'AgentAction':
                    print(f"⚙️  TOOL K8S INVOCATO : {getattr(action, 'tool', 'Sconosciuto')}")
                    print("📦 PAYLOAD JSON      :")
                    import pprint
                    pprint.pprint(getattr(action, 'tool_input', {}), indent=4)
                    
                    # Stampiamo il pensiero dell'agente prima di usare il tool
                    if hasattr(action, 'log') and action.log:
                        thought = action.log.split('Action:')[0].strip()
                        print(f"🧠 RAGIONAMENTO      : {thought}")
                        
                elif class_name == 'AgentFinish':
                    print("✅ TASK COMPLETATO (AgentFinish)")
                    # Non stampiamo tutto il testo qui perché CrewAI lo formatterà in verde alla fine
                    
        except Exception as e:
            print(f"⚠️ Errore silente nella callback di audit: {e}")
            
        print("="*60 + "\n")


    # ==========================================
    # 1. L'Investigatore (Triage)
    # ==========================================
    triage_agent = Agent(
        role='L1 SRE Incident Commander',
        goal='Parse raw monitoring alerts into structured incident briefs, identifying the blast radius and affected system components.',
        backstory=(
            "You are the first line of defense in a modern Cloud-Native reliability team. "
            "Your job is not to solve the problem, but to structure the chaos. "
            "You ingest raw telemetry and alerts, extract the exact target entities (Namespaces, Pods, Nodes, etc.), "
            "evaluate the severity, and summarize the observable symptoms for the diagnostic team."
        ),
        llm=local_llm,
        verbose=True
    )

    triage_task = Task(
        description=(
            f"Analyze this incoming telemetry/alert: {alert_context}. "
            "1. Extract the failing component(s) (e.g., Namespace, Pod, Service). "
            "2. Identify the primary symptom (e.g., CrashLoop, HighCPU, OOM). "
            "3. Assess the business/system impact based on the severity. "
            "Output a concise Incident Brief."
        ),
        expected_output="A structured Incident Brief identifying the exact target resources, symptoms, and severity.",
        agent=triage_agent
    )

    # ==========================================
    # 2. L'Analista (Cloud Architect)
    # ==========================================
    analysis_agent = Agent(
        role='Senior Cloud Ops Diagnostician',
        goal='Conduct a systematic root cause analysis by dynamically interrogating cluster state, telemetry, and related configurations.',
        backstory=(
            "You are a methodical Kubernetes and Cloud infrastructure expert. You do not guess; you gather evidence. "
            "You follow a strict diagnostic loop: Symptom -> Hypothesis -> Fetch Data -> Validate. "
            "CRITICAL SYSTEM CONSTRAINT: You must aggressively protect your context window. Whenever you use tools to fetch logs, events, or lists of resources, "
            "you MUST use parameters (like 'tailLines', 'limit', or grep-like filters) to restrict the output to a maximum of 15-20 lines/items. "
            "Remember that a failing component is often a victim of a misconfiguration elsewhere (e.g., missing Services, invalid ConfigMaps, or bad manifests). "
            "Investigate the ecosystem around the failing component."
        ),
        llm=local_llm,
        mcps=[kubernetes_mcp], 
        step_callback=k8s_action_callback,
        verbose=True
    )

    analysis_task = Task(
        description=(
            "Based on the Incident Brief, find the root cause of the failure. "
            "1. Formulate initial hypotheses based on the symptom. "
            "2. Use your MCP tools to inspect the target component's state, recent events, and limited logs (MAX 15 lines). "
            "3. SYSTEMATIC DISCOVERY RULE: If the logs indicate ANY connection issue, DNS resolution failure (ENOTFOUND), or missing endpoint, "
            "you MUST actively interrogate the cluster to discover the correct endpoints. "
            "Do this by using your tools to list the existing 'Services' and 'ConfigMaps' in the namespace. "
            "4. Cross-reference the failed connection attempt from the logs with the actual Services you discovered to find the mismatch. "
            "5. Conclude with a definitive, evidence-based root cause, explicitly naming the correct configurations if a mismatch is found."
        ),
        expected_output="A comprehensive diagnostic report detailing the evidence found, the root cause, and the correct target variables/endpoints discovered in the cluster.",
        agent=analysis_agent
    )

    # ==========================================
    # 3. Il Risolutore (DevOps Engineer)
    # ==========================================
    remediation_agent = Agent(
        role='GitOps Automation Engineer',
        goal='Translate the diagnostic root cause into precise, committable Infrastructure-as-Code (IaC) patches and open a GitHub PR.',
        backstory=(
            "You are a strict DevOps engineer operating in a Zero-Touch, GitOps-driven environment. "
            "You NEVER execute imperative state-changing commands on the cluster. "
            "PROCEDURE: "
            "1. Identify the target repository and the erroneous value from the Architect's report. "
            "2. DO NOT GUESS FILE PATHS BLINDLY. Use repository search tools (like search_code or get_directory_contents)."
            "3. Use 'get_file_content' to read the actual broken manifest. "
            "4. Generate the FULL, modified YAML content. "
            "5. Use 'create_gitops_pull_request' to open the PR with a professional title and the Architect's report as the body."
        ),
        llm=local_llm,
        mcps=[github_mcp], # <--- GLI DIAMO LE MANI!
        step_callback=k8s_action_callback, # Usiamo la stessa callback per vedere cosa fa
        verbose=True
    )

    remediation_task = Task(
        description=(
            "Review the root cause analysis provided by the Cloud Architect. "
            "Your objective is to physically open a Pull Request to fix the infrastructure state. "
            "ENVIRONMENT VARIABLES: "
            "TARGET_GITHUB_REPO: 'Lebroms/cloudops_shoes' "  
            "EXECUTION WORKFLOW: "
            "1. Search the TARGET_GITHUB_REPO to find the exact file path containing the misconfiguration. You can search for the resource name ) or the wrong value. " # (e.g., Kubernetes YAMLs, Terraform .tf files, Dockerfiles, or ConfigMaps)
            "2. Once you have the exact file path, use the 'get_file_content' tool to fetch its raw content. "
            "3. Analyze the raw code and apply a surgical fix to resolve the root cause WITHOUT altering unrelated configurations. "
            "4. Use the 'create_gitops_pull_request' tool on the TARGET_GITHUB_REPO to open the PR with the updated file content. "
            "5. Make sure the PR title is professional and the body summarizes the architectural fix."
        ),
        expected_output="A success message confirming the Pull Request was created, explicitly including the GitHub URL.",
        agent=remediation_agent
    )

    # ==========================================
    # ORCHESTRAZIONE DELLA CREW
    # ==========================================
    sre_crew = Crew(
        agents=[triage_agent, analysis_agent, remediation_agent],
        tasks=[triage_task, analysis_task, remediation_task],
        process=Process.sequential # L'output di un task diventa il contesto del successivo
    )

    try:
        print("🧠 [AIOps] Avvio motore AI: Qwen 2.5 Coder 7B (via Ollama)...")
        # L'esecuzione è sincrona, ma FastAPI usa un threadpool per non bloccare il server
        risultato = sre_crew.kickoff()
        print("✅ [AIOps] Analisi completata con successo.")
        
        # Restituiamo il JSON a n8n. CrewAI restituisce un oggetto, usiamo .raw per il testo puro.
        return {
            "status": "success", 
            "pod_target": alert.pod,
            "report": risultato.raw
        }
    except Exception as e:
        print(f"❌ [AIOps] Errore critico durante l'esecuzione della Crew: {str(e)}")
        raise HTTPException(status_code=500, detail="Errore interno del motore AI durante l'analisi.")

# ==========================================
# 4. AVVIO DEL SERVER
# ==========================================
if __name__ == "__main__":
    print("🌐 Avvio del server FastAPI sulla porta 8000...")
    # Avvia il server in ascolto su tutte le interfacce di rete (0.0.0.0)
    uvicorn.run(app, host="0.0.0.0", port=8000)