# github_mcp_server.py
import os
import time
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from github import Github, Auth

# Carica il token da .env
load_dotenv()
github_token = os.environ.get("GITHUB_TOKEN")
if not github_token:
    raise ValueError("GITHUB_TOKEN not found in environment variables.")

# Inizializza il client GitHub
auth = Auth.Token(github_token)
gh = Github(auth=auth)

# Inizializza il Server MCP
mcp = FastMCP("GitOps_GitHub_Server")

@mcp.tool()
def search_repository_code(repo_name: str, query: str) -> str:
    """
    Searches for a specific text query within the repository's code.
    Useful for finding where a specific variable, K8s object name, or misconfiguration exists.
    Args:
        repo_name: The full name of the repository (e.g., "owner/repo-name").
        query: The string to search for.
    """
    try:
        # GitHub search API richiede il repo nel formato query
        full_query = f"{query} repo:{repo_name}"
        results = gh.search_code(full_query)
        
        if results.totalCount == 0:
            return f"No results found for '{query}' in {repo_name}."
        
        # Estraiamo i path dei primi 5 risultati per non saturare il context window
        paths = [item.path for item in results[:5]]
        return f"Found '{query}' in the following files: {', '.join(paths)}"
    except Exception as e:
        return f"ERROR searching code: {str(e)}"

@mcp.tool()
def list_directory_contents(repo_name: str, path: str = "") -> str:
    """
    Lists the files and folders inside a specific directory of the repository.
    Leave path empty ("") to list the root directory.
    Args:
        repo_name: The full name of the repository.
        path: The folder path to inspect (e.g., "k8s" or "backend/src").
    """
    try:
        repo = gh.get_repo(repo_name)
        contents = repo.get_contents(path)
        
        # Se il path è un file e non una cartella
        if not isinstance(contents, list):
            return f"'{path}' is a file, not a directory. Use get_file_content to read it."
            
        items = []
        for c in contents:
            item_type = "DIR " if c.type == "dir" else "FILE"
            items.append(f"[{item_type}] {c.path}")
            
        return "Directory contents:\n" + "\n".join(items)
    except Exception as e:
        return f"ERROR listing directory '{path}': {str(e)}"

@mcp.tool()
def get_file_content(repo_name: str, file_path: str) -> str:
    """
    Retrieves the current raw content of a specific file from the target GitHub repository.
    Always use this tool BEFORE proposing any changes to understand the current configuration state and architecture of the file.
    Args:
        repo_name: The full name of the repository (e.g., "owner/repo-name").
        file_path: The exact path to the file within the repository (e.g., "path/to/file.yaml").
    """
    try:
        repo = gh.get_repo(repo_name)
        # Recupera il file dal branch principale
        file_content = repo.get_contents(file_path)
        return file_content.decoded_content.decode('utf-8')
    except Exception as e:
        return f"ERROR retrieving file {file_path}: {str(e)}"

@mcp.tool()
def create_gitops_pull_request(
    repo_name: str, 
    file_path: str, 
    new_file_content: str, 
    pr_title: str, 
    pr_body: str
) -> str:
    """
    Creates a new branch, commits the modified file, and opens a Pull Request on GitHub.
    Use this tool ONLY after you have completely prepared the new file content and ensured it adheres to GitOps best practices (e.g., avoiding configuration drift).
    Args:
        repo_name: The full name of the repository (e.g., "owner/repo-name").
        file_path: The exact path of the file to modify.
        new_file_content: The complete, updated file content to be committed. Do not use diffs or placeholders.
        pr_title: A concise, professional title for the Pull Request.
        pr_body: A detailed Markdown explanation of why this PR is necessary, including the diagnostic root cause.
    """
    try:
        repo = gh.get_repo(repo_name)
        
        # 1. Trova il branch di default (solitamente 'main' o 'master') 
        default_branch = repo.default_branch
        base_ref = repo.get_git_ref(f"heads/{default_branch}")
        
        # 2. Crea un nuovo branch con un nome univoco basato sul timestamp
        new_branch_name = f"aiops-fix-{int(time.time())}"
        repo.create_git_ref(ref=f"refs/heads/{new_branch_name}", sha=base_ref.object.sha)
        
        # 3. Ottieni il file attuale per avere il suo SHA (necessario per l'update su GitHub)
        file_obj = repo.get_contents(file_path, ref=default_branch)
        
        # 4. Esegui il commit sul nuovo branch
        commit_message = pr_title
        repo.update_file(
            path=file_path,
            message=commit_message,
            content=new_file_content,
            sha=file_obj.sha,
            branch=new_branch_name
        )
        
        # 5. Apri la Pull Request dal nuovo branch verso il default_branch
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=new_branch_name,
            base=default_branch
        )
        
        return f"SUCCESS: Pull Request created successfully! URL: {pr.html_url}"
    except Exception as e:
        return f"CRITICAL ERROR creating Pull Request: {str(e)}"

if __name__ == "__main__":
    # Avvia il server sul protocollo Stdio
    mcp.run()