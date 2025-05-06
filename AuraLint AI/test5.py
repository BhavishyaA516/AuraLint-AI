import psycopg2
from psycopg2 import Error
import ast
import traceback
import logging
import google.generativeai as genai
import re
import subprocess
import io
import os
import platform
from contextlib import redirect_stdout, redirect_stderr

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = "AIzaSyCfZzpfygluvpTyqGANIgdRpiilug9xur4"
DB_PARAMS = {
    "dbname": "pgql",
    "user": "pgql",
    "password": "postgres",
    "host": "3.110.135.2",
    "port": "5432"
}

# Initialize Gemini
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-pro')
    logger.info("Gemini initialized successfully")
except Exception as e:
    logger.error(f"Gemini initialization failed: {e}")

# Database Functions (unchanged)
def init_db():
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_analysis_logs (
                id SERIAL PRIMARY KEY,
                language VARCHAR(20) NOT NULL,
                original_code TEXT NOT NULL,
                corrected_code TEXT NOT NULL,
                error_report TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                error_count INTEGER
            );""")
        conn.commit()
        logger.info("Database initialized successfully")
        return True
    except Error as e:
        logger.error(f"Database initialization failed: {e}")
        return False
    finally:
        if conn:
            conn.close()

def save_to_db(language, original_code, corrected_code, error_report, error_count):
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO code_analysis_logs 
            (language, original_code, corrected_code, error_report, error_count) 
            VALUES (%s, %s, %s, %s, %s)
            """, 
            (language, original_code, corrected_code, error_report, error_count))
        conn.commit()
        logger.info("Saved to database")
        return True
    except Error as e:
        logger.error(f"Database save failed: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Error Detection and Fixing Functions (unchanged)
def detect_python_errors(code):
    errors = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        errors.append({"type": "SyntaxError", "line": e.lineno, "offset": e.offset, "message": str(e)})
        return errors
    
    try:
        f = io.StringIO()
        with redirect_stdout(f), redirect_stderr(f):
            exec(code, {})
        output = f.getvalue()
        if output and "error" in output.lower():
            errors.append({"type": "RuntimeOutput", "message": f"Unexpected output: {output}"})
    except Exception as e:
        errors.append({"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()})
    
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if isinstance(node.right, ast.Num) and node.right.n == 0:
                errors.append({"type": "LogicalError", "line": node.lineno, "message": "Potential division by zero"})
    
    return errors if errors else None

def extract_public_class_name(code):
    match = re.search(r"public\s+class\s+(\w+)", code)
    return match.group(1) if match else "Temp"

def detect_java_errors(code):
    errors = []
    class_name = extract_public_class_name(code)
    java_file = f"{class_name}.java"
    
    try:
        with open(java_file, "w") as f:
            f.write(code)
        result = subprocess.run(['javac', java_file], capture_output=True, text=True, timeout=5)
        if result.stderr:
            errors.append({"type": "CompilationError", "message": result.stderr})
        
        if not errors and "main" in code:
            run_result = subprocess.run(['java', class_name], capture_output=True, text=True, timeout=5)
            if run_result.stderr:
                errors.append({"type": "RuntimeError", "message": run_result.stderr})
            elif run_result.stdout and "exception" in run_result.stdout.lower():
                errors.append({"type": "RuntimeOutput", "message": f"Unexpected output: {run_result.stdout}"})
    except subprocess.TimeoutExpired:
        errors.append({"type": "TimeoutError", "message": "Execution timed out"})
    except Exception as e:
        errors.append({"type": "RuntimeError", "message": str(e)})
    finally:
        if os.path.exists(java_file):
            os.remove(java_file)
        if os.path.exists(f"{class_name}.class"):
            os.remove(f"{class_name}.class")
    
    if " / 0" in code:
        errors.append({"type": "LogicalError", "message": "Potential division by zero"})
    
    return errors if errors else None

def detect_c_errors(code):
    errors = []
    exe_name = "temp.exe" if platform.system() == "Windows" else "./temp"
    
    try:
        gcc_check = subprocess.run(['gcc', '--version'], capture_output=True, text=True)
        if gcc_check.returncode != 0:
            errors.append({"type": "EnvironmentError", "message": "GCC not found. Please ensure GCC is installed and added to PATH."})
            return errors

        with open("temp.c", "w") as f:
            f.write(code)
        result = subprocess.run(['gcc', '-o', 'temp', 'temp.c'], capture_output=True, text=True, timeout=5)
        if result.stderr:
            errors.append({"type": "CompilationError", "message": result.stderr})
        
        if not errors:
            run_result = subprocess.run([exe_name], capture_output=True, text=True, timeout=5)
            if run_result.stderr:
                errors.append({"type": "RuntimeError", "message": run_result.stderr})
            elif run_result.stdout and "error" in run_result.stdout.lower():
                errors.append({"type": "RuntimeOutput", "message": f"Unexpected output: {run_result.stdout}"})
    except subprocess.TimeoutExpired:
        errors.append({"type": "TimeoutError", "message": "Execution timed out"})
    except Exception as e:
        errors.append({"type": "RuntimeError", "message": str(e)})
    finally:
        for file in ["temp.c", "temp.exe" if platform.system() == "Windows" else "temp"]:
            if os.path.exists(file):
                os.remove(file)
    
    if " / 0" in code:
        errors.append({"type": "LogicalError", "message": "Potential division by zero"})
    
    return errors if errors else None

def analyze_code_structure(code, language):
    analysis = {'potential_issues': []}
    
    if language == "Python":
        try:
            tree = ast.parse(code)
            analysis['variables'] = set()
            analysis['functions'] = []
            analysis['undefined_vars'] = set()
            defined_vars = set()
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    if isinstance(node.ctx, ast.Store):
                        defined_vars.add(node.id)
                    elif isinstance(node.ctx, ast.Load):
                        if node.id not in defined_vars and node.id not in __builtins__.__dict__:
                            analysis['undefined_vars'].add(node.id)
                elif isinstance(node, ast.FunctionDef):
                    analysis['functions'].append(node.name)
                elif isinstance(node, ast.For) or isinstance(node, ast.While):
                    analysis['potential_issues'].append(f"Possible infinite loop at line {node.lineno}")
        except Exception as e:
            analysis['error'] = f"Structural analysis failed: {str(e)}"
    
    elif language == "Java":
        analysis['classes'] = []
        analysis['methods'] = []
        if "public class" not in code:
            analysis['potential_issues'].append("Missing public class declaration")
        if "main" not in code:
            analysis['potential_issues'].append("Missing main method")
        if "while(true)" in code.lower() or "for(;;)" in code:
            analysis['potential_issues'].append("Possible infinite loop detected")
    
    elif language == "C":
        analysis['functions'] = []
        if "main" not in code:
            analysis['potential_issues'].append("Missing main function")
        if "while(1)" in code or "for(;;)" in code:
            analysis['potential_issues'].append("Possible infinite loop detected")
    
    return analysis

def call_gemini_for_fix(code, language, errors, structural_analysis):
    try:
        error_summary = []
        if errors:
            for error in errors:
                error_summary.append(f"{error['type']}: {error['message']}")
        if structural_analysis.get('undefined_vars'):
            error_summary.append(f"Undefined variables: {', '.join(structural_analysis['undefined_vars'])}")
        if structural_analysis.get('potential_issues'):
            error_summary.append(f"Potential issues: {', '.join(structural_analysis['potential_issues'])}")

        prompt = "Analyze this " + language + " code with reported errors and provide:\n" + \
                "1. Corrected version\n" + \
                "2. Detailed error analysis\n" + \
                "3. Fix explanations\n\n" + \
                "Reported Issues:\n" + \
                (('\n'.join(error_summary)) if error_summary else 'No errors detected, check for potential improvements') + "\n\n" + \
                language + " Code:\n" + \
                code + "\n\n" + \
                "Format your response as:\n\n" + \
                "### Corrected Code:\n" + \
                "[code here]\n\n" + \
                "### Error Analysis:\n" + \
                "- Found: [list of errors]\n" + \
                "- Fixes: [list of corrections]\n" + \
                "- Suggestions: [improvements]\n\n" + \
                "If you cannot generate a corrected version, explicitly state why and return the original code with an explanation."

        response = model.generate_content(prompt)
        result = response.text
        
        corrected = re.search(r"### Corrected Code:\s*(.*?)(?=\n###|\Z)", result, re.DOTALL)
        analysis = re.search(r"### Error Analysis:\s*(.*)", result, re.DOTALL)
        
        if not corrected:
            return code, f"Failed to extract corrected code from response:\n{result}"
        
        corrected_code = corrected.group(1).strip()
        analysis_text = analysis.group(1).strip() if analysis else "Analysis not found"
        
        if corrected_code == code and error_summary:
            return code, f"AI failed to correct the code. Analysis:\n{analysis_text}"
            
        return corrected_code, analysis_text
    except Exception as e:
        logger.error(f"Gemini API error: {str(e)}")
        return code, f"API Error: {str(e)}"

# Main Function for Flask
def fix_code(code, language):
    if not code.strip():
        return code, "No code provided", 0

    if language == "Python":
        errors = detect_python_errors(code)
    elif language == "Java":
        errors = detect_java_errors(code)
    elif language == "C":
        errors = detect_c_errors(code)
    else:
        return code, "Unsupported language", 0

    structural_analysis = analyze_code_structure(code, language)
    
    error_count = len(errors) if errors else 0
    error_count += len(structural_analysis.get('undefined_vars', set())) + len(structural_analysis.get('potential_issues', []))

    report = []
    if errors:
        for error in errors:
            report.append(f"{error['type']}: {error['message']}")
    if structural_analysis.get('undefined_vars'):
        report.append(f"Potential undefined variables: {', '.join(structural_analysis['undefined_vars'])}")
    if structural_analysis.get('potential_issues'):
        report.append(f"Potential issues: {', '.join(structural_analysis['potential_issues'])}")
    if not report:
        report.append("No immediate errors detected, checking for potential improvements...")
    
    corrected_code, ai_analysis = call_gemini_for_fix(code, language, errors, structural_analysis)
    
    full_report = "\n".join(report) + f"\n\nAI Analysis:\n{ai_analysis}"
    
    # Save to database
    init_db()
    save_to_db(language, code, corrected_code, full_report, error_count)
    
    return corrected_code, full_report, error_count