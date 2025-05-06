import psycopg2
from psycopg2 import Error
import ast
import javalang
import logging
import google.generativeai as genai
from hashlib import md5
import re

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
            CREATE TABLE IF NOT EXISTS code_plag (
                id SERIAL PRIMARY KEY,
                language VARCHAR(10) NOT NULL,
                original_code TEXT NOT NULL,
                cleaned_code TEXT,
                plagiarism_score FLOAT,
                analysis TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

def save_to_db(language, original_code, cleaned_code, plagiarism_score, analysis):
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO code_plag 
            (language, original_code, cleaned_code, plagiarism_score, analysis) 
            VALUES (%s, %s, %s, %s, %s)
            """, 
            (language, original_code, cleaned_code, plagiarism_score, analysis))
        conn.commit()
        logger.info("Saved to database")
        return True
    except Error as e:
        logger.error(f"Database save failed: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Plagiarism Detection and Fixing Functions (unchanged)
def analyze_code_structure(code, language):
    try:
        if language == "python":
            tree = ast.parse(code)
            analysis = {'functions': [], 'classes': [], 'imports': [], 'code_hash': md5(code.encode()).hexdigest(), 'structure': []}
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['functions'].append(node.name)
                    analysis['structure'].append(f"func:{node.name}")
                elif isinstance(node, ast.ClassDef):
                    analysis['classes'].append(node.name)
                    analysis['structure'].append(f"class:{node.name}")
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imp = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                    analysis['imports'].append(imp)
                    analysis['structure'].append(f"import:{imp}")
            return analysis

        elif language == "java":
            tree = javalang.parse.parse(code)
            analysis = {'functions': [], 'classes': [], 'imports': [], 'code_hash': md5(code.encode()).hexdigest(), 'structure': []}
            for path, node in tree:
                if isinstance(node, javalang.tree.ClassDeclaration):
                    analysis['classes'].append(node.name)
                    analysis['structure'].append(f"class:{node.name}")
                elif isinstance(node, javalang.tree.MethodDeclaration):
                    analysis['functions'].append(node.name)
                    analysis['structure'].append(f"method:{node.name}")
                elif isinstance(node, javalang.tree.Import):
                    analysis['imports'].append(node.path)
                    analysis['structure'].append(f"import:{node.path}")
            return analysis

        elif language == "c":
            analysis = {'functions': [], 'classes': [], 'imports': [], 'code_hash': md5(code.encode()).hexdigest(), 'structure': []}
            func_pattern = r"(int|void|char|float|double)\s+(\w+)\s*\([^)]*\)\s*{"
            include_pattern = r"#include\s*[<\"](.+)[>\"]"
            analysis['functions'] = re.findall(func_pattern, code)
            analysis['imports'] = re.findall(include_pattern, code)
            analysis['structure'] = [f"func:{f[1]}" for f in analysis['functions']] + [f"include:{i}" for i in analysis['imports']]
            return analysis

    except Exception as e:
        return {'error': f"Code analysis failed for {language}: {str(e)}"}

def check_plagiarism(code, analysis, language):
    common_patterns = {
        'python': {
            'bubble_sort': ['def bubble_sort', 'for i in range', 'for j in range', 'if arr[j] >'],
            'fibonacci': ['def fib', 'if n <=', 'return n', 'return fib(n-1) + fib(n-2)'],
        },
        'java': {
            'bubble_sort': ['public void bubbleSort', 'for(int i', 'for(int j', 'if(arr[j] >'],
            'fibonacci': ['public int fib', 'if(n <=', 'return fib(n-1) + fib(n-2)'],
        },
        'c': {
            'bubble_sort': ['void bubbleSort', 'for(i =', 'for(j =', 'if(arr[j] >'],
            'fibonacci': ['int fib', 'if(n <=', 'return fib(n-1) + fib(n-2)'],
        }
    }
    
    code_lines = code.split('\n')
    plagiarism_score = 0
    matches = []
    patterns = common_patterns.get(language, {})
    
    for pattern_name, pattern in patterns.items():
        match_count = sum(1 for p in pattern if any(p in line for line in code_lines))
        similarity = match_count / len(pattern) * 100
        if similarity > 60:
            plagiarism_score += similarity
            matches.append(f"{pattern_name}: {similarity:.1f}% similar")
    
    return plagiarism_score / len(patterns) if matches else 0, matches

def call_gemini_for_alternative(code, analysis, plagiarism_info, language):
    try:
        prompt = f"""Given this {language} code that shows potential plagiarism ({plagiarism_info}):
        
Code Structure:
- Functions/Methods: {', '.join(analysis.get('functions', []))}
- Classes: {', '.join(analysis.get('classes', []))}
- Imports/Includes: {', '.join(analysis.get('imports', []))}

Please provide:
1. A unique alternative implementation with similar functionality in {language}
2. Explanation of changes
3. Why this avoids plagiarism

Format your response as:
### Alternative Code:
[code here]

### Explanation:
- Changes: [list]
- Originality: [explanation]
- Functionality: [verification]"""

        response = model.generate_content(prompt)
        result = response.text
        
        alt_code = re.search(r"### Alternative Code:\s*(.*?)(?=\n###|\Z)", result, re.DOTALL)
        explanation = re.search(r"### Explanation:\s*(.*)", result, re.DOTALL)
        
        if alt_code and explanation:
            return alt_code.group(1).strip(), explanation.group(1).strip()
        return None, "Unexpected response format"
    except Exception as e:
        logger.error(f"Gemini API error: {str(e)}")
        return None, f"API Error: {str(e)}"

# Main Function for Flask
def check_plagiarism_and_fix(code, language):
    if not code.strip():
        return code, "No code provided", 0
    
    analysis = analyze_code_structure(code, language)
    if 'error' in analysis:
        return code, analysis['error'], 0
    
    plagiarism_score, matches = check_plagiarism(code, analysis, language)
    
    if plagiarism_score > 20:
        alternative_code, explanation = call_gemini_for_alternative(code, analysis, matches, language)
        if alternative_code:
            debug_info = f"Plagiarism Score: {plagiarism_score:.1f}%\nMatches found: {', '.join(matches)}\n\n{explanation}"
            # Save to database
            init_db()
            save_to_db(language, code, alternative_code, plagiarism_score, debug_info)
            return alternative_code, debug_info, plagiarism_score
        else:
            debug_info = f"Plagiarism Score: {plagiarism_score:.1f}%\nMatches found: {', '.join(matches)}\n\nFailed to generate alternative: {explanation}"
            # Save to database
            init_db()
            save_to_db(language, code, code, plagiarism_score, debug_info)
            return code, debug_info, plagiarism_score
    else:
        debug_info = f"Plagiarism Score: {plagiarism_score:.1f}%\nNo significant plagiarism detected"
        # Save to database
        init_db()
        save_to_db(language, code, code, plagiarism_score, debug_info)
        return code, debug_info, plagiarism_score