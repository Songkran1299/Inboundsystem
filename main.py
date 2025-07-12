import os
import re
import json
import time
from flask import Flask, render_template, request, redirect, url_for, session, flash
import fitz # PyMuPDF
from PIL import Image
import pytesseract
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = 'your_very_secret_and_unguessable_key_v3_final'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

UPLOAD_FOLDER = 'static'
DB_FILE = 'database.json'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_USERS = ["admin", "wirun", "pemika", "songkran", "santisuk", "garan", "chaiwut", "pormharit"]

def load_db():
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'meta' not in data: data['meta'] = {'creators': [], 'location_writers': []}
            if 'tasks' not in data: data['tasks'] = {}
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tasks": {}, "meta": {"creators": [], 'location_writers': []}}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def parse_document_text(text):
    po_number, company_name, date, item_list = "ไม่พบ", "ไม่พบ", "ไม่พบ", []
    po_match = re.search(r"P\d{10}", text)
    if po_match: po_number = po_match.group(0)
    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if date_match: date = date_match.group(1)
    company_match = re.search(r"บริษัท\s*3\s*เอ็ม\s*ประเทศไทย\s*จํากัด", text, re.IGNORECASE)
    if company_match: company_name = "บริษัท 3เอ็ม ประเทศไทย จํากัด"
    item_no_match = re.search(r"(8151-XT\d+)", text)
    if item_no_match:
        item_no, item_desc, quantity, location = item_no_match.group(1), "ตลับกรองไอระเหยสารเคมีและปรอท", "480.00", "ไม่พบ"
        loc_match = re.search(r"ห่อ\s+([A-Z0-9-]+)", text)
        if loc_match: location = loc_match.group(1)
        item_data = {
            'item_id': 'item_0', 'item_desc': f"{item_no} {item_desc}", 'original_quantity': quantity,
            'original_location': location, 'edited_quantity': quantity, 'edited_location': location,
            'is_active': True, 'manual_remark': '', 'location_writer': '', 'remarks': '', 'remarks_color': ''
        }
        item_list.append(item_data)
    requires_review = (po_number == "ไม่พบ" or not item_list)
    return po_number, company_name, date, item_list, requires_review

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username_input = request.form['username'].lower()
        if username_input in ALLOWED_USERS:
            session['username'] = username_input
            session.permanent = True
            return redirect(url_for('index'))
        else:
            flash('ชื่อผู้ใช้นี้ไม่ได้รับอนุญาต', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'username' not in session: return redirect(url_for('login'))
    db = load_db()
    all_tasks_dict = db.get("tasks", {})
    meta_data = db.get("meta", {})
    creators = meta_data.get('creators', [])
    search_query = request.args.get('search', '').lower()
    filtered_tasks = [task for task in all_tasks_dict.values() if not search_query or 
                      (search_query in task['po_number'].lower() or 
                       search_query in task.get('invoice_number', '').lower())]
    filtered_tasks.sort(key=lambda t: t.get('id', ''), reverse=True)
    priority_tasks = [t for t in filtered_tasks if t.get('admin_priority')]
    normal_tasks = [t for t in filtered_tasks if not t.get('admin_priority')]
    final_tasks = []
    for task in priority_tasks + normal_tasks:
        task['has_edits'] = any(item.get('remarks_color') == 'red' for item in task.get('item_list', []))
        writers = sorted(list({item.get('location_writer') for item in task.get('item_list', []) if item.get('location_writer')}))
        task['writers_display'] = ' / '.join(writers)
        final_tasks.append(task)
    return render_template('index.html', tasks=final_tasks, creators=creators, username=session.get('username'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'username' not in session: return redirect(url_for('login'))
    file = request.files.get('pdf_file')
    if not file or file.filename == '': return redirect(request.url)
    db = load_db()
    creator_name = request.form.get('creator_name', '').strip()
    if creator_name and creator_name not in db['meta']['creators']:
        db['meta']['creators'].append(creator_name)
    task_id = "task_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}.pdf")
    file.save(pdf_path)
    full_text, image_path = "", ""
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            if i == 0:
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}.png")
                pix.save(image_path)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            full_text += pytesseract.image_to_string(img, lang='tha+eng') + "\n"
    po, company, date, item_list, requires_review = parse_document_text(full_text)
    task_data = {
        'id': task_id, 'po_number': po, 'company_name': company, 'date': date,
        'status': 'รอดำเนินการ', 'admin_priority': False, 'creator_name': creator_name,
        'invoice_number': '', 'item_list': item_list, 'image_path': os.path.basename(image_path) if image_path else '',
        'requires_review': requires_review, 'created_at': time.time()
    }
    db["tasks"][task_id] = task_data
    save_db(db)
    return redirect(url_for('index'))

@app.route('/task/<task_id>')
def show_task(task_id):
    if 'username' not in session: return redirect(url_for('login'))
    db = load_db()
    task_data = db.get("tasks", {}).get(task_id)
    if not task_data: return redirect(url_for('index'))
    meta_data = db.get("meta", {})
    return render_template('task.html', task=task_data, location_writers=meta_data.get('location_writers', []), username=session.get('username'))

@app.route('/submit_item_update/<task_id>', methods=['POST'])
def submit_item_update(task_id):
    if 'username' not in session: return redirect(url_for('login'))
    db = load_db()
    task_data = db.get("tasks", {}).get(task_id)
    if not task_data: return redirect(url_for('index'))

    item_id_to_update = request.form['item_id']
    location_writer = request.form.get('location_writer', '').strip()
    if location_writer and location_writer not in db['meta']['location_writers']:
        db['meta']['location_writers'].append(location_writer)

    for item in task_data['item_list']:
        if item['item_id'] == item_id_to_update:
            item.update({
                'is_active': 'is_active' in request.form,
                'manual_remark': request.form.get('manual_remark', ''),
                'location_writer': location_writer,
                'edited_location': request.form['location'],
                'edited_quantity': request.form['quantity']
            })
            location_changed = item['edited_location'] != item['original_location']
            quantity_changed = item['edited_quantity'] != item['original_quantity']
            if location_changed and quantity_changed: item['remarks'] = 'แก้ L+Q'
            elif location_changed: item['remarks'] = 'แก้ L'
            elif quantity_changed: item['remarks'] = 'แก้ Q'
            else: item['remarks'] = 'ไม่แก้'
            item['remarks_color'] = 'red' if (location_changed or quantity_changed) else 'green'
            break

    if all(item.get('remarks') for item in task_data['item_list']):
        task_data['status'] = 'เสร็จสิ้น'

    db["tasks"][task_id] = task_data
    save_db(db)

    return redirect(url_for('show_task', task_id=task_id, saved_item=item_id_to_update))

@app.route('/daily_report')
def daily_report():
    if 'username' not in session: return redirect(url_for('login'))
    db = load_db()
    tasks_today = [task for task in db.get("tasks", {}).values() if datetime.fromtimestamp(task.get('created_at', 0)).date() == date.today()]
    total_bills = len(tasks_today)
    creator_summary, writer_summary = {}, {}
    for task in tasks_today:
        creator = task.get('creator_name', 'N/A')
        creator_summary[creator] = creator_summary.get(creator, 0) + 1
        for item in task.get('item_list', []):
            writer = item.get('location_writer')
            if writer: writer_summary[writer] = writer_summary.get(writer, 0) + 1
    return render_template('report.html', report_date=datetime.now().strftime("%d %B %Y"),
                           total_bills=total_bills, creator_summary=creator_summary,
                           writer_summary=writer_summary, username=session.get('username'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=81)