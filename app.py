from flask import Flask, request, jsonify, render_template, g, send_from_directory, abort, make_response
from flask_cors import CORS
import sqlite3
import os
import uuid
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

app = Flask(__name__, static_folder='../gender_reveal_app/build', static_url_path='/')

# Serve React app
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    file_path = os.path.join(app.static_folder, path)
    if os.path.exists(file_path):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

DATABASE = 'gender_reveal.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

@app.route('/api/vote', methods=['POST'])
def submit_vote():
    data = request.get_json()
    name = data.get('name', 'Anonymous')
    vote = data.get('vote')

    # Get client IP address
    if request.headers.get('X-Forwarded-For'):
        ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        ip_address = request.headers.get('X-Real-IP')
    else:
        ip_address = request.remote_addr

    voter_id = request.cookies.get('voter_id')
    
    existing_vote = False

    db = get_db()

    if not voter_id:
        # First time visitor
        voter_id = str(uuid.uuid4())
    else:
        # Check if this voter_id has already voted
        cursor1 = db.cursor()
        cursor1.execute('SELECT id FROM votes WHERE voter_id = ?', (voter_id,))
        existing_vote = cursor1.fetchone()
    
    if not vote or vote not in ['boy', 'girl']:
        return jsonify({'error': 'Invalid vote'}), 400
    
    # Check if gender has been revealed already
    
    cursor = db.cursor()
    cursor.execute('SELECT revealed FROM reveal WHERE id = 1')
    reveal_info = cursor.fetchone()
    
    if reveal_info and reveal_info['revealed']:
        return jsonify({'error': 'Voting has closed as gender has been revealed'}), 403
    
    if existing_vote:
        return jsonify({'error': 'You have already voted from this device/location'}), 409
    
    # Continue with the vote submission
    cursor.execute('INSERT INTO votes (name, vote, ip_address, voter_id) VALUES (?, ?, ?, ?)', 
                  (name, vote, ip_address, voter_id))
    db.commit()
    
    response = make_response(jsonify({"status": "success"}))
    response.set_cookie('voter_id', voter_id, max_age=60*60*24)  # 1 day expiry
    return response

@app.route('/api/results', methods=['GET'])
def get_results():
    db = get_db()
    cursor = db.cursor()
    
    # Get current reveal status
    cursor.execute('SELECT revealed, actual_gender FROM reveal WHERE id = 1')
    reveal_info = cursor.fetchone()
    revealed = reveal_info['revealed'] if reveal_info else False
    actual_gender = reveal_info['actual_gender'] if reveal_info else None
    
    # Get vote counts
    cursor.execute('SELECT vote, COUNT(*) as count FROM votes GROUP BY vote')
    votes = cursor.fetchall()
    
    results = {
        'boy': 0,
        'girl': 0,
        'revealed': revealed,
        'actual_gender': actual_gender if revealed else None,
        'total_votes': 0
    }
    
    for row in votes:
        results[row['vote']] = row['count']
        results['total_votes'] += row['count']
    
    # If revealed, include correct/incorrect counts
    if revealed and actual_gender:
        cursor.execute('SELECT name, vote FROM votes')
        all_votes = cursor.fetchall()
        
        correct_guesses = []
        incorrect_guesses = []
        
        for vote in all_votes:
            if vote['vote'] == actual_gender:
                correct_guesses.append(vote['name'])
            else:
                incorrect_guesses.append(vote['name'])
        
        results['correct_guesses'] = correct_guesses
        results['incorrect_guesses'] = incorrect_guesses
    
    return jsonify(results)

@app.route('/api/admin/reveal', methods=['POST'])
def reveal():
    data = request.get_json()
    admin_key = data.get('admin_key')
    gender = data.get('gender')
    
    # In a real app, validate admin_key properly
    # This is just a simple example
    if admin_key != 'your_secret_admin_key':
        return jsonify({'error': 'Unauthorized'}), 401
    
    if gender not in ['boy', 'girl']:
        return jsonify({'error': 'Invalid gender'}), 400
    
    db = get_db()
    cursor = db.cursor()
    
    # Check if reveal record exists
    cursor.execute('SELECT * FROM reveal WHERE id = 1')
    if cursor.fetchone():
        cursor.execute('UPDATE reveal SET revealed = 1, actual_gender = ? WHERE id = 1', (gender,))
    else:
        cursor.execute('INSERT INTO reveal (id, revealed, actual_gender) VALUES (1, 1, ?)', (gender,))
    
    db.commit()
    
    return jsonify({'success': True})

@app.route('/api/admin/reset', methods=['POST'])
def reset_results():
    data = request.get_json()
    admin_key = data.get('admin_key')
    
    # Validate admin key
    if admin_key != 'your_secret_admin_key':
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    # Clear all votes
    cursor.execute('DELETE FROM votes')
    
    # Reset reveal status
    cursor.execute('UPDATE reveal SET revealed = 0, actual_gender = NULL WHERE id = 1')
    if cursor.rowcount == 0:  # If no row exists yet
        cursor.execute('INSERT INTO reveal (id, revealed, actual_gender) VALUES (1, 0, NULL)')
    
    db.commit()
    
    return jsonify({'success': True, 'message': 'All data has been reset'})

@app.route('/api/votes', methods=['GET'])
def get_votes():
    conn = get_db()
    votes = conn.execute('SELECT * FROM votes ORDER BY timestamp DESC').fetchall()
    return jsonify([dict(row) for row in votes])

@app.route('/api/delete-vote', methods=['POST'])
def delete_vote():
    vote_id = request.json.get('id')
    if not vote_id:
        return jsonify({'error': 'Missing vote ID'}), 400

    conn = get_db()
    conn.execute('DELETE FROM votes WHERE id = ?', (vote_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)