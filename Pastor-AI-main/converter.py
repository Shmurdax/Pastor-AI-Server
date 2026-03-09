import os
import re
import subprocess
import fitz  # PyMuPDF
import pypandoc

# --- CONFIGURATION ---
# Change this to where YOUR LibreOffice is installed if different
LIBREOFFICE_PATH = r"C:\Program Files\LibreOffice\program\soffice.exe"

def master_converter(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    # PASS 1: Modernize Legacy Files (.doc and .wps)
    print("🛠️  Pass 1: Modernizing legacy files using LibreOffice...")
    for filename in os.listdir(input_dir):
        if filename.lower().endswith(('.doc', '.wps', '.rtf')):
            file_path = os.path.join(input_dir, filename)
            print(f"   > Converting {filename} to .docx...")
            try:
                # Use LibreOffice 'headless' command to convert
                subprocess.run([
                    LIBREOFFICE_PATH, 
                    '--headless', 
                    '--convert-to', 'docx', 
                    '--outdir', input_dir, 
                    file_path
                ], check=True, capture_output=True)
            except Exception as e:
                print(f"   ❌ LibreOffice failed on {filename}: {e}")

    # PASS 2: Convert Modern Files to Markdown
    print("\n📝 Pass 2: Converting to Markdown...")
    for filename in os.listdir(input_dir):
        file_path = os.path.join(input_dir, filename)
        ext = os.path.splitext(filename)[1].lower()
        output_name = os.path.splitext(filename)[0] + ".md"
        output_path = os.path.join(output_dir, output_name)

        try:
            # Handle PDF
            if ext == '.pdf':
                print(f"   > [PDF] {filename}")
                doc = fitz.open(file_path)
                content = "\n".join([page.get_text() for page in doc])
                save_md(output_path, normalize_text(content))

            # Handle DOCX (including the ones we just created)
            elif ext == '.docx':
                print(f"   > [DOCX] {filename}")
                # Pandoc is perfect for docx -> markdown
                content = pypandoc.convert_file(file_path, 'md', format='docx')
                save_md(output_path, normalize_text(content))

        except Exception as e:
            print(f"   ❌ Error converting {filename}: {e}")

    print("\n✅ All done! Check your 'converted_markdown' folder.")

def normalize_text(text):
    # 1. Normalize line endings to standard Unix style
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 2. Strip Markdown Bold and Italics 
    # Must do this FIRST so the script can see the "naked" structural markers
    text = re.sub(r'\*+|_+', '', text)

    # 3. Strip Superscripts (e.g., ^42^ from Bible verse numbers)
    text = re.sub(r'\^\d+\^', '', text)

    # 4. Remove "Sticky" Verse Numbers (e.g., 'Sabbath1' or '2And')
    # Prevents words from being merged with verse numbers
    text = re.sub(r'(?<=[a-z])\d+|(?<!\.)\d+(?=[A-Z])', ' ', text)

    # 5. WEB NOISE REMOVAL
    # Removes specific artifacts found in converted legacy documents
    noise_patterns = [r'REPORT\s+THIS\s+AD', r'ADVERTISEMENTS']
    for pattern in noise_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # 6. Remove standalone page numbers and clean up escaped markdown characters (Artifacts)
    text = text.replace('\\.', '.')
    text = text.replace('\\"', '"')
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
    
    # 7. Add double newlines to structural markers
    # This prepares the text for the save_md function to add # and ## headers
    markers = [r'TEXT:', r'INTRO:', r'CONCLUSION:', r'^[IVXLC]+\.', r'^\d+\.']
    for marker in markers:
        text = re.sub(f'({marker})', r'\n\n\1', text, flags=re.MULTILINE)

    # 8. Final Whitespace Cleanup
    # Collapses multiple newlines into 2, and multiple spaces into 1
    text = re.sub(r'\n{3,}', '\n\n', text) 
    text = re.sub(r'[ \t]{2,}', ' ', text)
    
    return text.strip()

def save_md(path, content):
    lines = content.split('\n')
    processed_lines = []
    found_h1 = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            processed_lines.append(line)
            continue

        # IDENTIFY HEADING 1 (The Title)
        # We look for the first non-numeric line that is ALL CAPS
        if not found_h1 and any(c.isalpha() for c in stripped) and stripped.isupper():
            processed_lines.append(f"# {stripped}")
            found_h1 = True
            continue

        # IDENTIFY HEADING 2 (Roman Numerals: I. II. III.)
        if re.match(r'^[IVXLC]+\.', stripped):
            processed_lines.append(f"## {stripped}")
        else:
            processed_lines.append(line)
            
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(processed_lines))

if __name__ == "__main__":
    INPUT = r"C:\Users\MC_Mill\Documents\GitHub\Pastor-AI-GUI\Pastor-AI-main\Pastor-Data"
    OUTPUT = r"C:\Users\MC_Mill\Documents\GitHub\Pastor-AI-GUI\Pastor-AI-main\converted_markdown"
    master_converter(INPUT, OUTPUT)