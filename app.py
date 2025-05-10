import os
import random
import hashlib
import pyodbc
from flask import Flask, render_template, redirect, url_for, request, session

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Directory for cover images
IMG_DIR = os.path.join(app.static_folder, 'imgs')

# -----------------------------
# Database helpers
# -----------------------------

def get_db_connection():
    conn = pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=localhost;'
        'DATABASE=mybookdb;'
        'Trusted_Connection=yes;'
    )
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Create categories table
    cur.execute(
        """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='categories' AND xtype='U')
           CREATE TABLE categories (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(255) UNIQUE,
                icon NVARCHAR(255) DEFAULT 'fa-book'
            )"""
    )

    # Insert default categories if table is empty
    cur.execute("IF NOT EXISTS (SELECT TOP 1 * FROM categories) SELECT 1 ELSE SELECT 0")
    if cur.fetchone()[0]:
        cur.execute("INSERT INTO categories (name, icon) VALUES ('Fiction', 'book')")
        cur.execute("INSERT INTO categories (name, icon) VALUES ('Science', 'flask')")
        cur.execute("INSERT INTO categories (name, icon) VALUES ('History', 'history')")
        cur.execute("INSERT INTO categories (name, icon) VALUES ('Technology', 'laptop-code')")

    cur.execute(
        """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='books' AND xtype='U')
           CREATE TABLE books (
                id INT IDENTITY(1,1) PRIMARY KEY,
                title NVARCHAR(255),
                author NVARCHAR(255),
                price FLOAT,
                cover_url NVARCHAR(512) DEFAULT NULL,
                category_id INT DEFAULT NULL,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
            )"""
    )

    # Check if category_id column exists in books table
    cur.execute(
        """IF NOT EXISTS (
               SELECT * FROM syscolumns
               WHERE id = OBJECT_ID('books') AND name = 'category_id'
           ) SELECT 1 ELSE SELECT 0
        """
    )

    # If column doesn't exist, add it
    if cur.fetchone()[0]:
        try:
            cur.execute("ALTER TABLE books ADD category_id INT DEFAULT NULL")
            cur.execute("ALTER TABLE books ADD CONSTRAINT FK_books_categories FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL")
        except:
            # Column might already exist or there might be other issues
            pass

    cur.execute(
        """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
           CREATE TABLE users (
                id INT IDENTITY(1,1) PRIMARY KEY,
                username NVARCHAR(255) UNIQUE,
                email NVARCHAR(255),
                password NVARCHAR(MAX),
                is_admin BIT DEFAULT 0
            )"""
    )

    # Check if email column exists in users table
    cur.execute(
        """IF NOT EXISTS (
               SELECT * FROM syscolumns
               WHERE id = OBJECT_ID('users') AND name = 'email'
           ) SELECT 1 ELSE SELECT 0
        """
    )

    # If column doesn't exist, add it
    if cur.fetchone()[0]:
        try:
            cur.execute("ALTER TABLE users ADD email NVARCHAR(255) DEFAULT NULL")
        except:
            # Column might already exist or there might be other issues
            pass

    cur.execute(
        """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='cart' AND xtype='U')
           CREATE TABLE cart (
                id INT IDENTITY(1,1) PRIMARY KEY,
                user_id INT,
                book_id INT,
                quantity INT DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            )"""
    )

    # Check if quantity column exists in cart table
    cur.execute(
        """IF NOT EXISTS (
               SELECT * FROM syscolumns
               WHERE id = OBJECT_ID('cart') AND name = 'quantity'
           ) SELECT 1 ELSE SELECT 0
        """
    )

    # If column doesn't exist, add it
    if cur.fetchone()[0]:
        try:
            cur.execute("ALTER TABLE cart ADD quantity INT DEFAULT 1")
            # Update existing records to have quantity = 1
            cur.execute("UPDATE cart SET quantity = 1 WHERE quantity IS NULL")
        except:
            # Column might already exist or there might be other issues
            pass

    conn.commit()
    conn.close()

# -----------------------------
# Authentication routes
# -----------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form.get('email', '').strip()
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()

        # Validate confirm password if provided
        confirm_password = request.form.get('confirm_password', '')
        if confirm_password and hashlib.sha256(confirm_password.encode()).hexdigest() != password:
            return render_template('register.html', error="Passwords do not match")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM users')
        is_admin = (cur.fetchone()[0] == 0)
        cur.execute(
            'INSERT INTO users (username, email, password, is_admin) VALUES (?, ?, ?, ?)',
            (username, email, password, is_admin)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT id, is_admin FROM users WHERE username = ? AND password = ?',
            (username, password)
        )
        user = cur.fetchone()
        conn.close()
        if user:
            session['user_id'] = user[0]
            session['is_admin'] = bool(user[1])
            session['username'] = username
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# -----------------------------
# Shop routes
# -----------------------------

def choose_random_cover():
    imgs = [f for f in os.listdir(IMG_DIR) if f.lower().endswith(('jpg','jpeg','png','webp'))]
    return f'imgs/{random.choice(imgs)}' if imgs else None

@app.route('/')
@app.route('/category/<int:category_id>')
@app.route('/search')
def home(category_id=None):
    conn = get_db_connection()
    cur = conn.cursor()

    # Get all categories
    cur.execute('SELECT * FROM categories')
    categories = cur.fetchall()

    # Get filter parameters
    search_query = request.args.get('q', '').strip()
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort_by = request.args.get('sort_by', 'default')
    sort_order = request.args.get('sort_order', 'asc')

    # Base query
    query = '''
        SELECT b.*, c.name as category_name, c.icon as category_icon
        FROM books b
        LEFT JOIN categories c ON b.category_id = c.id
        WHERE 1=1
    '''
    params = []

    # Add filters
    if category_id:
        query += ' AND b.category_id = ?'
        params.append(category_id)
    
    if search_query:
        search_param = f'%{search_query}%'
        query += ' AND (b.title LIKE ? OR b.author LIKE ? OR c.name LIKE ?)'
        params.extend([search_param, search_param, search_param])
    
    if min_price is not None:
        query += ' AND b.price >= ?'
        params.append(min_price)
    
    if max_price is not None:
        query += ' AND b.price <= ?'
        params.append(max_price)

    # Add sorting
    if sort_by == 'price':
        query += f' ORDER BY b.price {sort_order}'
    elif sort_by == 'title':
        query += f' ORDER BY b.title {sort_order}'
    else:
        query += ' ORDER BY b.id DESC'  # Default sorting

    # Execute query
    cur.execute(query, params)
    raw = cur.fetchall()
    conn.close()

    books = []
    for b in raw:
        try:
            # Try accessing as attributes
            book_id = b.id
            title = b.title
            author = b.author
            price = b.price
            cover_url = b.cover_url
            category_id = getattr(b, 'category_id', None)
            category_name = getattr(b, 'category_name', None)
            category_icon = getattr(b, 'category_icon', 'book')
        except:
            # Try accessing as indices
            book_id = b[0]
            title = b[1]
            author = b[2]
            price = b[3]
            cover_url = b[4] if len(b) > 4 else None
            category_id = b[5] if len(b) > 5 else None
            category_name = b[6] if len(b) > 6 else None
            category_icon = b[7] if len(b) > 7 else 'book'

        cover = cover_url if cover_url else choose_random_cover()

        books.append({
            'id': book_id,
            'title': title,
            'author': author,
            'price': price,
            'cover': cover,
            'category_id': category_id,
            'category_name': category_name,
            'category_icon': category_icon
        })

    # Get active category name if filtering
    active_category = None
    if category_id:
        for cat in categories:
            if cat.id == category_id:
                active_category = cat.name
                break
    else:
        active_category = None  # تأكيد أن القيمة None دائماً

    # Get min and max prices for filter range
    if books:
        min_book_price = min(book['price'] for book in books)
        max_book_price = max(book['price'] for book in books)
    else:
        min_book_price = 0
        max_book_price = 100

    return render_template(
        'index.html',
        books=books,
        categories=categories,
        active_category=active_category,
        search_query=search_query,
        min_price=min_price,
        max_price=max_price,
        min_book_price=min_book_price,
        max_book_price=max_book_price,
        sort_by=sort_by,
        sort_order=sort_order
    )

@app.route('/add_to_cart/<int:book_id>', methods=['GET', 'POST'])
def add_to_cart(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    quantity = 1
    if request.method == 'POST' and 'quantity' in request.form:
        try:
            quantity = int(request.form['quantity'])
            if quantity < 1:
                quantity = 1
        except:
            quantity = 1

    conn = get_db_connection()
    cur = conn.cursor()

    # Check if the book is already in the cart
    cur.execute('SELECT id, quantity FROM cart WHERE user_id = ? AND book_id = ?',
                (session['user_id'], book_id))
    existing_item = cur.fetchone()

    if existing_item:
        # Update quantity if the book is already in the cart
        new_quantity = existing_item.quantity + quantity
        cur.execute('UPDATE cart SET quantity = ? WHERE id = ?',
                    (new_quantity, existing_item.id))
    else:
        # Add new item to cart
        cur.execute('INSERT INTO cart (user_id, book_id, quantity) VALUES (?, ?, ?)',
                    (session['user_id'], book_id, quantity))

    conn.commit()
    conn.close()

    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        '''SELECT c.id as cart_id, b.id as book_id, b.title, b.author, b.price,
                 b.cover_url, c.quantity, b.category_id,
                 cat.name as category_name, cat.icon as category_icon
          FROM cart c
          JOIN books b ON c.book_id=b.id
          LEFT JOIN categories cat ON b.category_id=cat.id
          WHERE c.user_id=?''',
        (session['user_id'],)
    )
    raw = cur.fetchall()
    conn.close()

    items = []
    for i in raw:
        try:
            # Try accessing as attributes
            cart_id = i.cart_id
            book_id = i.book_id
            title = i.title
            author = i.author
            price = i.price
            cover_url = i.cover_url
            quantity = i.quantity
            category_name = getattr(i, 'category_name', None)
            category_icon = getattr(i, 'category_icon', 'book')
        except:
            # Try accessing as indices
            cart_id = i[0]
            book_id = i[1]
            title = i[2]
            author = i[3]
            price = i[4]
            cover_url = i[5]
            quantity = i[6]
            category_name = i[8] if len(i) > 8 else None
            category_icon = i[9] if len(i) > 9 else 'book'

        cover = cover_url if cover_url else choose_random_cover()

        items.append({
            'cart_id': cart_id,
            'book_id': book_id,
            'title': title,
            'author': author,
            'price': price,
            'cover': cover,
            'quantity': quantity,
            'category_name': category_name,
            'category_icon': category_icon,
            'item_total': price * quantity
        })

    total = sum(item['item_total'] for item in items)
    return render_template('cart.html', cart_items=items, total_price=total)


@app.route('/update_cart_quantity', methods=['POST'])
def update_cart_quantity():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    cart_id = request.form.get('cart_id')
    action = request.form.get('action')

    if not cart_id or not action:
        return redirect(url_for('cart'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Get current quantity
    cur.execute('SELECT quantity FROM cart WHERE id = ? AND user_id = ?',
                (cart_id, session['user_id']))
    result = cur.fetchone()

    if not result:
        conn.close()
        return redirect(url_for('cart'))

    current_quantity = result.quantity if hasattr(result, 'quantity') else result[0]

    if action == 'increase':
        new_quantity = current_quantity + 1
        cur.execute('UPDATE cart SET quantity = ? WHERE id = ? AND user_id = ?',
                   (new_quantity, cart_id, session['user_id']))
    elif action == 'decrease':
        if current_quantity > 1:
            new_quantity = current_quantity - 1
            cur.execute('UPDATE cart SET quantity = ? WHERE id = ? AND user_id = ?',
                       (new_quantity, cart_id, session['user_id']))
        else:
            # Remove item if quantity would be less than 1
            cur.execute('DELETE FROM cart WHERE id = ? AND user_id = ?',
                       (cart_id, session['user_id']))
    elif action == 'remove':
        cur.execute('DELETE FROM cart WHERE id = ? AND user_id = ?',
                   (cart_id, session['user_id']))

    conn.commit()
    conn.close()

    return redirect(url_for('cart'))

@app.route('/clear_cart')
def clear_cart():
    if 'user_id' in session:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM cart WHERE user_id=?', (session['user_id'],))
        conn.commit()
        conn.close()
    return redirect(url_for('cart'))

# -----------------------------
# Admin panel
# -----------------------------

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('is_admin'):
        return redirect(url_for('home'))
    conn = get_db_connection()
    cur = conn.cursor()
    images = [f'imgs/{f}' for f in os.listdir(IMG_DIR)
              if f.lower().endswith(('jpg','jpeg','png','webp'))]

    # Get all categories
    cur.execute('SELECT * FROM categories')
    categories = cur.fetchall()

    if request.method == 'POST':
        action = request.form.get('action')

        # Add new category
        if action == 'add_category':
            category_name = request.form['category_name'].strip()
            category_icon = request.form['category_icon'].strip()
            if category_name:
                cur.execute('INSERT INTO categories (name, icon) VALUES (?, ?)',
                           (category_name, category_icon))
                conn.commit()

        # Delete category
        elif action == 'delete_category':
            cur.execute('DELETE FROM categories WHERE id=?', (request.form['category_id'],))
            conn.commit()

        # Edit category
        elif action == 'edit_category':
            cur.execute('UPDATE categories SET name=?, icon=? WHERE id=?',
                       (request.form['category_name'].strip(),
                        request.form['category_icon'].strip(),
                        request.form['category_id']))
            conn.commit()

        # Add book with category
        elif action == 'add_book':
            category_id = request.form.get('category_id')
            if category_id and category_id != '':
                category_id = int(category_id)
            else:
                category_id = None

            cur.execute('INSERT INTO books (title, author, price, cover_url, category_id) VALUES (?, ?, ?, ?, ?)',
                        (request.form['title'].strip(),
                         request.form['author'].strip(),
                         float(request.form['price']),
                         request.form.get('cover_url') or None,
                         category_id))
            conn.commit()

        # Delete book
        elif action == 'delete_book':
            cur.execute('DELETE FROM books WHERE id=?', (request.form['book_id'],))
            conn.commit()
            cur.execute('SELECT COUNT(*) FROM books')
            if cur.fetchone()[0] == 0:
                cur.execute('DBCC CHECKIDENT (books, RESEED, 0)')
                conn.commit()

        # Edit book with category
        elif action == 'edit_book':
            category_id = request.form.get('category_id')
            if category_id and category_id != '':
                category_id = int(category_id)
            else:
                category_id = None

            cur.execute('UPDATE books SET title=?, author=?, price=?, cover_url=?, category_id=? WHERE id=?',
                        (request.form['title'].strip(),
                         request.form['author'].strip(),
                         float(request.form['price']),
                         request.form.get('cover_url') or None,
                         category_id,
                         request.form['book_id']))
            conn.commit()

        # User management
        elif action == 'delete_user':
            cur.execute('DELETE FROM users WHERE id=?', (request.form['user_id'],))
            conn.commit()
            cur.execute('SELECT ISNULL(MAX(id), 0) FROM users')
            max_id = cur.fetchone()[0]
            cur.execute('DBCC CHECKIDENT (users, RESEED, ?)', (max_id,))
            conn.commit()
        elif action == 'edit_user':
            cur.execute('UPDATE users SET username=?, email=?, is_admin=? WHERE id=?',
                        (request.form['username'].strip(),
                         request.form.get('email', '').strip(),
                         1 if request.form.get('is_admin') == 'on' else 0,
                         request.form['user_id']))
            conn.commit()

    # Get updated data
    cur.execute('SELECT * FROM users')
    users = cur.fetchall()

    # Get books with category information
    cur.execute('''
        SELECT b.*, c.name as category_name
        FROM books b
        LEFT JOIN categories c ON b.category_id = c.id
    ''')
    books = cur.fetchall()

    # Get updated categories
    cur.execute('SELECT * FROM categories')
    categories = cur.fetchall()

    conn.close()
    return render_template('admin.html', users=users, books=books, images=images, categories=categories)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)