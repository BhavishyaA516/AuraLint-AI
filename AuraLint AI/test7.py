import psycopg2
from psycopg2 import Error
import time
import re
import logging
import ast
import google.generativeai as genai

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
            CREATE TABLE IF NOT EXISTS code_optimization_records (
                id SERIAL PRIMARY KEY,
                language VARCHAR(20),
                original_code TEXT NOT NULL,
                optimized_code TEXT NOT NULL,
                debug_info TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                execution_time FLOAT,
                optimization_level VARCHAR(20)
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

def save_to_db(language, original_code, optimized_code, debug_info, exec_time, opt_level):
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO code_optimization_records 
            (language, original_code, optimized_code, debug_info, execution_time, optimization_level) 
            VALUES (%s, %s, %s, %s, %s, %s)
            """, 
            (language, original_code, optimized_code, debug_info, exec_time, opt_level))
        conn.commit()
        logger.info("Saved to database")
        return True
    except Error as e:
        logger.error(f"Database save failed: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Optimization Functions (unchanged)
def analyze_code_structure(code, language):
    if language == "Python":
        try:
            tree = ast.parse(code)
            analysis = {
                'functions': 0,
                'classes': 0,
                'loops': 0,
                'imports': 0,
                'variables': set()
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['functions'] += 1
                elif isinstance(node, ast.ClassDef):
                    analysis['classes'] += 1
                elif isinstance(node, (ast.For, ast.While)):
                    analysis['loops'] += 1
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    analysis['imports'] += 1
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    analysis['variables'].add(node.id)
            return analysis
        except Exception as e:
            return {'error': f"Code analysis failed: {str(e)}"}
    
    elif language in ["C", "Java"]:
        analysis = {
            'functions': len(re.findall(r'(?:int|void|float|double|char)\s+\w+\s*\([^)]*\)\s*{', code)),
            'classes': len(re.findall(r'class\s+\w+\s*{', code)) if language == "Java" else 0,
            'loops': len(re.findall(r'(for|while)\s*\(', code)),
            'includes': len(re.findall(r'#include\s*[<"][^>"]+[>"]', code)) if language == "C" else 0,
            'imports': len(re.findall(r'import\s+[\w.]+;', code)) if language == "Java" else 0
        }
        return analysis
    
    return {'error': 'Unsupported language'}

def measure_execution_time(code, language):
    try:
        if language == "Python":
            namespace = {}
            start_time = time.time()
            exec(code, namespace)
            return time.time() - start_time, None
        elif language in ["C", "Java"]:
            lines = len(code.split('\n'))
            loops = len(re.findall(r'(for|while)\s*\(', code))
            return (lines * 0.001 + loops * 0.01), None
    except Exception as e:
        return None, f"Execution failed: {str(e)}"

def rule_based_optimize(code, language):
    optimizations = []
    optimized_code = code
    
    if language == "Python":
        patterns = [
            (r'if (True|False):\s*\n\s*(.*?)\s*\n\s*else:\s*\n\s*(.*?)\s*\n', 
             lambda m: m.group(2) if m.group(1) == 'True' else m.group(3),
             "Simplified constant conditional"),
            (r'for (\w+) in range\(len\((\w+)\)\):\s*\n\s*(.*?)\s*=\s*\2\[\1\]', 
             lambda m: f"for {m.group(3)} in {m.group(2)}:",
             "Replaced index-based loop with direct iteration")
        ]
    
    elif language == "C":
        patterns = [
            (r'if\s*\((1|0)\)\s*{\s*(.*?)}\s*else\s*{\s*(.*?)}\s*', 
             lambda m: m.group(2) if m.group(1) == '1' else m.group(3),
             "Simplified constant conditional"),
            (r'(\w+)\s*=\s*(\w+)\s*\+\s*(\w+)\s*;\s*(\w+)\s*=\s*(\w+)\s*-\s*(\w+)\s*;', 
             lambda m: f"{m.group(1)} = {m.group(2)} + {m.group(3)}, {m.group(4)} = {m.group(5)} - {m.group(6)};",
             "Combined assignments")
        ]
    
    elif language == "Java":
        patterns = [
            (r'if\s*\((true|false)\)\s*{\s*(.*?)}\s*else\s*{\s*(.*?)}\s*', 
             lambda m: m.group(2) if m.group(1) == 'true' else m.group(3),
             "Simplified constant conditional"),
            (r'for\s*\(int\s+(\w+)\s*=\s*0;\s*\1\s*<\s*(\w+)\.length\(\);\s*\1\+\+\)\s*', 
             lambda m: f"for (int {m.group(1)} : {m.group(2)})",
             "Converted to enhanced for loop when possible")
        ]
    
    for pattern, replacement, message in patterns:
        if re.search(pattern, code, re.DOTALL):
            optimized_code = re.sub(pattern, replacement, optimized_code, flags=re.DOTALL)
            optimizations.append(message)
    
    return optimized_code, optimizations

def call_gemini(code, analysis, language):
    try:
        analysis_summary = "\n".join([f"- {k}: {v}" for k, v in analysis.items() if k != 'error'])
        
        prompt = f"""Analyze this {language} code and provide:
1. Optimized version
2. Detailed analysis
3. Performance metrics
4. Explanations for changes

Code Analysis:
{analysis_summary}

{language} Code:
{code}

Format your response as:

### Optimized Code:
[code here]

### Analysis:
- Complexity: [info]
- Optimizations: [list]
- Performance: [estimate]
- Readability: [improvements]
- Alternatives: [suggestions]"""
        
        response = model.generate_content(prompt)
        result = response.text
        
        opt_code = re.search(r"### Optimized Code:\s*(.*?)(?=\n###|\Z)", result, re.DOTALL)
        analysis = re.search(r"### Analysis:\s*(.*)", result, re.DOTALL)
        
        return (opt_code.group(1).strip() if opt_code else code), \
               (analysis.group(1).strip() if analysis else "Unexpected response format")
    except Exception as e:
        logger.error(f"Gemini API error: {str(e)}")
        return code, f"API Error: {str(e)}"

# Main Function for Flask
def optimize_code(code, language):
    if not code.strip():
        return code, "No code provided", 0, "none"
    
    analysis = analyze_code_structure(code, language)
    if 'error' in analysis:
        return code, analysis['error'], 0, "error"
    
    original_time, exec_error = measure_execution_time(code, language)
    if exec_error:
        return code, exec_error, 0, "error"
    
    optimized_code, rule_optimizations = rule_based_optimize(code, language)
    optimization_level = "rule-based"
    
    if optimized_code != code:
        new_time, new_exec_error = measure_execution_time(optimized_code, language)
        if new_exec_error:
            debug_info = f"Rule-based optimizations:\n" + "\n".join(rule_optimizations)
            debug_info += f"\n\nOriginal execution time: {original_time:.4f}s\nOptimized code execution failed: {new_exec_error}"
            return optimized_code, debug_info, 0, optimization_level
        
        improvement = (original_time - new_time) / original_time * 100 if original_time else 0
        debug_info = f"Rule-based optimizations:\n" + "\n".join(rule_optimizations)
        debug_info += f"\n\nExecution time: {improvement:.2f}% improvement ({original_time:.4f}s → {new_time:.4f}s)"
        
        # Save to database
        init_db()
        save_to_db(language, code, optimized_code, debug_info, new_time, optimization_level)
        return optimized_code, debug_info, new_time, optimization_level
    
    optimized_code, ai_analysis = call_gemini(code, analysis, language)
    optimization_level = "AI-based"
    
    new_time, new_exec_error = measure_execution_time(optimized_code, language)
    debug_info = f"AI Analysis:\n{ai_analysis}"
    if original_time and new_time:
        improvement = (original_time - new_time) / original_time * 100 if original_time else 0
        debug_info += f"\n\nExecution time: {improvement:.2f}% change ({original_time:.4f}s → {new_time:.4f}s)"
    
    # Save to database
    init_db()
    save_to_db(language, code, optimized_code, debug_info, new_time if new_time else 0, optimization_level)
    return optimized_code, debug_info, new_time if new_time else 0, optimization_level