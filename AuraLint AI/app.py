from flask import Flask, request, render_template, send_file
import test5
import test7
import test8
import test9
import io

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

# Error Fixer
@app.route('/fix-errors', methods=['GET', 'POST'])
def fix_errors():
    if request.method == 'POST':
        code = request.form['code']
        language = request.form['language']
        corrected_code, error_report, error_count = test5.fix_code(code, language)
        return render_template('fix_errors.html', 
                             code=code, 
                             result=corrected_code, 
                             report=error_report, 
                             error_count=error_count, 
                             language=language)
    return render_template('fix_errors.html', code=None, result=None, report=None, error_count=None)

# Optimizer
@app.route('/optimize', methods=['GET', 'POST'])
def optimize():
    if request.method == 'POST':
        code = request.form['code']
        language = request.form['language']
        optimized_code, debug_info, exec_time, opt_level = test7.optimize_code(code, language)
        return render_template('optimize.html', 
                             code=code, 
                             result=optimized_code, 
                             report=debug_info, 
                             exec_time=exec_time, 
                             opt_level=opt_level, 
                             language=language)
    return render_template('optimize.html', code=None, result=None, report=None, exec_time=None, opt_level=None)

# Plagiarism Checker
@app.route('/check-plagiarism', methods=['GET', 'POST'])
def check_plagiarism():
    if request.method == 'POST':
        code = request.form['code']
        language = request.form['language'].lower()  # Ensure lowercase for consistency
        cleaned_code, debug_info, plagiarism_score = test8.check_plagiarism_and_fix(code, language)
        return render_template('plagiarism.html', 
                             code=code, 
                             result=cleaned_code, 
                             report=debug_info, 
                             score=plagiarism_score, 
                             language=language)
    return render_template('plagiarism.html', code=None, result=None, report=None, score=None)

# Documentation Generator
@app.route('/document', methods=['GET', 'POST'])
def document():
    if request.method == 'POST':
        code = request.form['code']
        language = request.form['language']
        documentation, pdf_buffer = test9.generate_documentation(code, language)
        if request.form.get('download') == 'pdf':
            pdf_buffer.seek(0)
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name='code_documentation.pdf',
                mimetype='application/pdf'
            )
        return render_template('document.html', 
                             code=code, 
                             result=documentation, 
                             language=language)
    return render_template('document.html', code=None, result=None)

if __name__ == '__main__':
    app.run(debug=True)