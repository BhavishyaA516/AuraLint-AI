import psycopg2
from psycopg2 import Error
import google.generativeai as genai
import logging
import ast
import re
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io

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

# Database Functions
def ensure_table_exists():
    """
    Ensure the code_documentation_logs table exists, creating it if necessary.
    Returns True if table exists or is created, False on failure.
    """
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'code_documentation_logs'
            );
        """)
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            logger.info("Creating code_documentation_logs table...")
            cursor.execute("""
                CREATE TABLE code_documentation_logs (
                    id SERIAL PRIMARY KEY,
                    language VARCHAR(20) NOT NULL,
                    original_code TEXT NOT NULL,
                    documentation TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            logger.info("code_documentation_logs table created successfully")
        else:
            logger.info("code_documentation_logs table already exists")
        
        return True
    except Error as e:
        logger.error(f"Failed to ensure table exists: {e}")
        return False
    finally:
        if conn:
            conn.close()

def save_to_db(language, original_code, documentation):
    """
    Save documentation to the database, ensuring table exists first.
    Returns True on success, False on failure.
    """
    conn = None
    try:
        # Ensure table exists before inserting
        if not ensure_table_exists():
            logger.error("Cannot save: Database table not available")
            return False
        
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO code_documentation_logs 
            (language, original_code, documentation) 
            VALUES (%s, %s, %s)
        """, 
        (language, original_code, documentation))
        conn.commit()
        logger.info("Saved to database successfully")
        return True
    except Error as e:
        logger.error(f"Database save failed: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Code Analysis
def analyze_code_structure(code, language):
    analysis = {'functions': [], 'classes': [], 'imports': []}
    
    if language == "Python":
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['functions'].append(node.name)
                elif isinstance(node, ast.ClassDef):
                    analysis['classes'].append(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imp = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                    analysis['imports'].append(imp)
        except Exception:
            pass
    
    elif language == "Java":
        class_pattern = r'class\s+(\w+)'
        method_pattern = r'(?:public|private|protected)?\s*(?:static)?\s*\w+\s+(\w+)\s*\([^)]*\)'
        import_pattern = r'import\s+[\w.]+;'
        analysis['classes'] = re.findall(class_pattern, code)
        analysis['functions'] = re.findall(method_pattern, code)
        analysis['imports'] = re.findall(import_pattern, code)
    
    elif language == "C":
        func_pattern = r"(int|void|char|float|double)\s+(\w+)\s*\([^)]*\)\s*{"
        include_pattern = r"#include\s*[<\"](.+)[>\"]"
        analysis['functions'] = [match[1] for match in re.findall(func_pattern, code)]
        analysis['imports'] = re.findall(include_pattern, code)
    
    return analysis

# Gemini AI for Documentation
def call_gemini_for_documentation(code, language, analysis):
    try:
        analysis_summary = "\n".join([
            f"Functions/Methods: {', '.join(analysis.get('functions', []))}",
            f"Classes: {', '.join(analysis.get('classes', []))}",
            f"Imports/Includes: {', '.join(analysis.get('imports', []))}"
        ])
        
        prompt = f"""Analyze this {language} code and generate documentation with:
1. Problem Statement
2. Input/Output Format
3. Constraints (if any)
4. Approach/Algorithm Explanation (include time/space complexity)
5. Code with Inline Comments
6. Example(s) with Explanation

Code Structure:
{analysis_summary}

{language} Code:
{code}

Format your response as:
### Problem Statement:
[description]

### Input/Output Format:
- Input: [description]
- Output: [description]

### Constraints:
[constraints or none]

### Approach/Algorithm:
- Logic: [explanation]
- Steps: [steps]
- Time Complexity: [complexity]
- Space Complexity: [complexity]

### Commented Code:
[code with comments]

### Example(s):
- Input: [input]
- Output: [output]
- Explanation: [explanation]"""
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error: {str(e)}")
        return f"Error generating documentation: {str(e)}"

# PDF Generation
def generate_pdf_documentation(documentation):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=inch, leftMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(name='Title', fontSize=16, leading=20, spaceAfter=12, textColor='#00ff9d')
    heading_style = ParagraphStyle(name='Heading', fontSize=14, leading=18, spaceAfter=10, spaceBefore=12, textColor='#00ff9d')
    body_style = ParagraphStyle(name='Body', fontSize=12, leading=14, spaceAfter=8)
    code_style = ParagraphStyle(name='Code', fontName='Courier', fontSize=10, leading=12, spaceAfter=8)
    
    story = []
    
    # Clean documentation to remove HTML-like tags
    clean_documentation = re.sub(r'<para>|</para>', '', documentation)
    
    # Parse documentation
    sections = re.split(r'###\s*([\w\s/]+):', clean_documentation)[1:]
    for i in range(0, len(sections), 2):
        title, content = sections[i].strip(), sections[i+1].strip()
        story.append(Paragraph(title, title_style if title == 'Problem Statement' else heading_style))
        if title == 'Commented Code':
            story.append(Preformatted(content, code_style))
        else:
            for line in content.strip().split('\n'):
                if line.startswith('- '):
                    story.append(Paragraph(line, body_style))
                else:
                    story.append(Paragraph(line, body_style))
        story.append(Spacer(1, 0.2 * inch))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# Main Function
def generate_documentation(code, language):
    if not code.strip():
        return "No code provided", None
    
    analysis = analyze_code_structure(code, language)
    documentation = call_gemini_for_documentation(code, language, analysis)
    
    # Save to database
    save_to_db(language, code, documentation)
    
    # Generate PDF
    pdf_buffer = generate_pdf_documentation(documentation)
    
    return documentation, pdf_buffer

# Initialize database on module load
ensure_table_exists()