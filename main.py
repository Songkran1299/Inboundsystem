    import os
    import re
    import json
    import time
    from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify # เพิ่ม jsonify
    import fitz # PyMuPDF
    from PIL import Image
    import pytesseract
    from datetime import datetime, timedelta, date
    import logging # เพิ่ม logging

    # ตั้งค่า Logging เพื่อให้เห็นข้อผิดพลาดใน Console ได้ชัดเจนขึ้น
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    app = Flask(__name__)
    app.secret_key = 'your_very_secret_and_unguessable_key_v3_final'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

    # --- จุดที่ 1: เปลี่ยน UPLOAD_FOLDER เป็น /tmp ---
    # **สำคัญ:** นี่คือการแก้ไขหลักเพื่อแก้ปัญหา PermissionError บน Cloud (Render/Replit)
    # ไฟล์ที่นี่เป็นชั่วคราว หากต้องการเก็บถาวรต้องใช้ Object Storage (S3) หรือ Persistent Disks
    UPLOAD_FOLDER = '/tmp' 
    # ไม่ต้องสร้างโฟลเดอร์สำหรับ /tmp เพราะมันมีอยู่แล้ว
    # if not os.path.exists(UPLOAD_FOLDER):
    #     os.makedirs(UPLOAD_FOLDER)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    DB_FILE = 'database.json' # ยังคงใช้ database.json เช่นเดิม

    # ตรวจสอบว่า DB_FILE สามารถเขียนได้หรือไม่ (ใน /tmp หรือที่อื่นที่ Render อนุญาต)
    # หาก DB_FILE อยู่ใน root folder เดียวกับ app.py ใน Replit อาจจะเขียนได้
    # แต่หาก Deploy บน Render แล้ว database.json ไม่ถูกเขียน ควรพิจารณาใช้ DB จริง
    def load_db():
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'meta' not in data: data['meta'] = {'creators': [], 'location_writers': []}
                if 'tasks' not in data: data['tasks'] = {}
                return data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error loading database.json: {e}", exc_info=True)
            # หาก DB_FILE หายไป หรืออ่านไม่ได้ จะสร้างโครงสร้างเริ่มต้นให้
            return {"tasks": {}, "meta": {"creators": [], 'location_writers': []}}

    def save_db(data):
        try:
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logging.info(f"Database saved to {DB_FILE}")
        except IOError as e:
            logging.error(f"Error saving database.json: {e}", exc_info=True)
            # ควรมีวิธีจัดการหากบันทึก DB ไม่ได้ เช่น แจ้งผู้ใช้
            flash('ไม่สามารถบันทึกข้อมูลได้ กรุณาลองใหม่ภายหลัง', 'error')


    # ตรวจสอบว่า Tesseract Engine พร้อมใช้งาน
    # บน Linux/Debian-based system (เช่นใน Replit/Render) ต้องติดตั้ง tesseract-ocr
    # apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-tha tesseract-ocr-eng
    try:
        pytesseract.get_tesseract_version()
        logging.info("Tesseract-OCR engine is available.")
    except pytesseract.TesseractNotFoundError:
        logging.error("Tesseract-OCR engine not found. Please install it on your system.")
        # คุณอาจต้องหยุดแอปหรือแจ้ง error ที่ชัดเจนกว่านี้หาก Tesseract จำเป็น
    except Exception as e:
        logging.error(f"Error checking Tesseract-OCR: {e}", exc_info=True)


    ALLOWED_USERS = ["admin", "wirun", "pemika", "songkran", "santisuk", "garan", "chaiwut", "pormharit"]

    def parse_document_text(text):
        po_number, company_name, date, item_list = "ไม่พบ", "ไม่พบ", "ไม่พบ", []
        po_match = re.search(r"P\d{10}", text)
        if po_match: po_number = po_match.group(0)
        date_match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
        if date_match: date = date_match.group(1)
        company_match = re.search(r"บริษัท\s*3\s*เอ็ม\s*ประเทศไทย\s*จํากัด", text, re.IGNORECASE)
        if company_match: company_name = "บริษัท 3เอ็ม ประเทศไทย จํากัด"
        # ใช้ re.findall เพื่อหา item_no หลายตัว ถ้ามี
        # item_no_matches = re.findall(r"(8151-XT\d+)", text) # หากมีหลายบรรทัด ให้วนลูป

        # โค้ดเดิมของคุณดูเหมือนจะหาแค่รายการเดียวต่อเอกสาร
        item_no_match = re.search(r"(8151-XT\d+)", text)
        if item_no_match:
            item_no, item_desc, quantity, location = item_no_match.group(1), "ตลับกรองไอระเหยสารเคมีและปรอท", "480.00", "ไม่พบ"
            loc_match = re.search(r"ห่อ\s+([A-Z0-9-]+)", text)
            if loc_match: location = loc_match.group(1)
            item_data = {
                'item_id': f'item_{len(item_list)}', # สร้าง item_id ให้ไม่ซ้ำกัน
                'item_desc': f"{item_no} {item_desc}", 
                'original_quantity': quantity,
                'original_location': location, 
                'edited_quantity': quantity, 
                'edited_location': location,
                'is_active': True, 
                'manual_remark': '', 
                'location_writer': '', # ต้องกำหนดค่านี้เมื่อมีการแก้ไข Item
                'remarks': '', 
                'remarks_color': ''
            }
            item_list.append(item_data)

        # เพิ่มการตรวจสอบ item_list หาก OCR ไม่พบข้อมูลที่คาดหวัง
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

        # --- จุดที่ 2: เพิ่ม try-except เพื่อดักจับข้อผิดพลาดในการอัปโหลด/ประมวลผล ---
        try:
            file = request.files.get('pdf_file') # ใช้ .get() เพื่อป้องกัน KeyError
            if not file or file.filename == '':
                logging.warning("No file or empty filename received from upload.")
                flash('กรุณาเลือกไฟล์ PDF ที่ถูกต้อง', 'error')
                return redirect(request.url) # หรือ redirect(url_for('index'))

            db = load_db()
            creator_name = request.form.get('creator_name', '').strip()
            if creator_name and creator_name not in db['meta']['creators']:
                db['meta']['creators'].append(creator_name)
                save_db(db) # บันทึก creator ใหม่ทันที

            task_id = "task_" + datetime.now().strftime("%Y%m%d_%H%M%S")

            # ใช้ os.path.join เพื่อสร้าง path ที่ถูกต้องสำหรับระบบปฏิบัติการ
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}.pdf")

            try:
                file.save(pdf_path)
                logging.info(f"PDF file '{file.filename}' saved to {pdf_path}")
            except IOError as e:
                logging.error(f"Error saving PDF file to {pdf_path}: {e}", exc_info=True)
                flash(f'ไม่สามารถบันทึกไฟล์ได้: {e}', 'error')
                return redirect(request.url) # หรือ return jsonify({"error": "Failed to save file"}), 500

            full_text, image_path = "", ""
            try:
                with fitz.open(pdf_path) as doc:
                    for i, page in enumerate(doc):
                        pix = page.get_pixmap(dpi=200) # เพิ่ม dpi เพื่อคุณภาพ OCR ที่ดีขึ้น
                        if i == 0: # บันทึกหน้าแรกเป็นรูปภาพ
                            image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}.png")
                            pix.save(image_path)
                            logging.info(f"Image saved to {image_path}")

                        # แปลง pixmap เป็น PIL Image และใช้ Tesseract
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        full_text += pytesseract.image_to_string(img, lang='tha+eng') + "\n"
                    logging.info(f"OCR completed for {pdf_path}. Extracted text length: {len(full_text)}")
            except Exception as e:
                logging.error(f"Error processing PDF with PyMuPDF/Tesseract: {e}", exc_info=True)
                flash(f'เกิดข้อผิดพลาดในการประมวลผล PDF หรือ OCR: {e}', 'error')
                # ควรลบไฟล์ PDF ที่บันทึกไว้หากประมวลผลไม่สำเร็จ
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                return redirect(request.url) # หรือ return jsonify({"error": "PDF processing failed"}), 500

            po, company, date, item_list, requires_review = parse_document_text(full_text)

            # หาก item_list ว่างเปล่า อาจต้องตรวจสอบอีกครั้งหรือตั้งค่า remarks ที่ชัดเจน
            if not item_list:
                logging.warning(f"No items found after parsing text for task {task_id}. Text: {full_text[:200]}...")
                # คุณอาจต้องการเพิ่ม item_list เริ่มต้นที่มีสถานะต้องรีวิว
                requires_review = True # บังคับให้ต้องรีวิว

            task_data = {
                'id': task_id, 
                'po_number': po, 
                'company_name': company, 
                'date': date,
                'status': 'รอดำเนินการ', # สถานะเริ่มต้น
                'admin_priority': False, 
                'creator_name': creator_name,
                'invoice_number': '', 
                'item_list': item_list, 
                'image_path': os.path.basename(image_path) if image_path else '',
                'requires_review': requires_review, 
                'created_at': time.time()
            }

            db["tasks"][task_id] = task_data
            save_db(db)
            flash('อัปโหลดและประมวลผลเอกสารสำเร็จ!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            logging.error(f"An unhandled error occurred in upload_file: {e}", exc_info=True)
            flash(f'เกิดข้อผิดพลาดที่ไม่คาดคิดในการอัปโหลด: {e}', 'error')
            return redirect(request.url) # หรือ return jsonify({"error": "Internal Server Error"}), 500


    @app.route('/task/<task_id>')
    def show_task(task_id):
        if 'username' not in session: return redirect(url_for('login'))
        db = load_db()
        task_data = db.get("tasks", {}).get(task_id)
        if not task_data: 
            flash('ไม่พบ Task ที่ระบุ', 'error')
            return redirect(url_for('index'))
        meta_data = db.get("meta", {})
        return render_template('task.html', task=task_data, location_writers=meta_data.get('location_writers', []), username=session.get('username'))

    @app.route('/submit_item_update/<task_id>', methods=['POST'])
    def submit_item_update(task_id):
        if 'username' not in session: return redirect(url_for('login'))
        db = load_db()
        task_data = db.get("tasks", {}).get(task_id)
        if not task_data: 
            flash('ไม่พบ Task ที่ระบุ', 'error')
            return redirect(url_for('index'))

        # --- จุดที่ 3: ป้องกัน KeyError ด้วย .get() ---
        item_id_to_update = request.form.get('item_id')
        if not item_id_to_update:
            logging.warning(f"item_id not found in form for task {task_id}.")
            flash('ไม่พบข้อมูล Item ที่จะอัปเดต', 'error')
            return redirect(url_for('show_task', task_id=task_id))

        location_writer = request.form.get('location_writer', '').strip()
        if location_writer and location_writer not in db['meta']['location_writers']:
            db['meta']['location_writers'].append(location_writer)
            save_db(db) # บันทึก location_writer ใหม่ทันที

        found_item = False
        for item in task_data['item_list']:
            if item['item_id'] == item_id_to_update:
                found_item = True

                # ใช้ .get() เพื่อป้องกัน KeyError และให้ค่า default ที่เหมาะสม
                edited_location = request.form.get('location', item.get('edited_location', ''))
                edited_quantity = request.form.get('quantity', item.get('edited_quantity', ''))

                # พยายามแปลง quantity เป็นตัวเลข หากไม่ใช่ ให้ใช้ค่าเดิม
                try:
                    edited_quantity = float(edited_quantity) # หรือ int() ถ้าเป็นจำนวนเต็มเท่านั้น
                except ValueError:
                    logging.warning(f"Invalid quantity format for item {item_id_to_update}: {edited_quantity}. Keeping original.")
                    edited_quantity = item.get('edited_quantity', 0.0) # ใช้ค่าเดิมหรือ 0.0 เป็น default

                item.update({
                    'is_active': 'is_active' in request.form, # checkbox จะส่งค่าก็ต่อเมื่อถูกเลือก
                    'manual_remark': request.form.get('manual_remark', ''),
                    'location_writer': location_writer,
                    'edited_location': edited_location,
                    'edited_quantity': edited_quantity
                })

                # ตรวจสอบการเปลี่ยนแปลงเทียบกับ original_location/quantity
                location_changed = item['edited_location'] != item['original_location']
                quantity_changed = item['edited_quantity'] != item['original_quantity']

                if location_changed and quantity_changed: item['remarks'] = 'แก้ L+Q'
                elif location_changed: item['remarks'] = 'แก้ L'
                elif quantity_changed: item['remarks'] = 'แก้ Q'
                else: item['remarks'] = 'ไม่แก้'
                item['remarks_color'] = 'red' if (location_changed or quantity_changed) else 'green'
                break # พบ item แล้ว ออกจาก loop

        if not found_item:
            logging.warning(f"Item with ID {item_id_to_update} not found in task {task_id}'s item_list.")
            flash('ไม่พบ Item ที่จะอัปเดตในรายการ Task นี้', 'error')
            return redirect(url_for('show_task', task_id=task_id))

        # ตรวจสอบสถานะ Task ว่าเสร็จสิ้นหรือไม่
        # ควรตรวจสอบจาก 'remarks' ของทุก item และ/หรือ 'requires_review'
        # หากทุก item มี remarks และไม่ต้องการรีวิวแล้ว ให้เปลี่ยน status
        # ตัวอย่าง:
        if all(item.get('remarks') and item.get('remarks') != '' for item in task_data['item_list']) and not task_data.get('requires_review', False):
            task_data['status'] = 'เสร็จสิ้น'
            logging.info(f"Task {task_id} status changed to 'เสร็จสิ้น'.")
        else:
            task_data['status'] = 'รอดำเนินการ' # หรือ 'รอรีวิว'

        db["tasks"][task_id] = task_data
        save_db(db)
        flash('อัปเดตข้อมูล Item สำเร็จ!', 'success')
        return redirect(url_for('show_task', task_id=task_id, saved_item=item_id_to_update))

    @app.route('/daily_report')
    def daily_report():
        if 'username' not in session: return redirect(url_for('login'))
        db = load_db()
        # ดึง created_at จาก timestamp ที่บันทึก
        tasks_today = [task for task in db.get("tasks", {}).values() 
                       if datetime.fromtimestamp(task.get('created_at', 0)).date() == date.today()]
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

