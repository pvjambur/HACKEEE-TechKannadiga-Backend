"""
Artist Backend Integration for Namma Karnataka
Complete endpoints for artist profile management, event discovery, and applications
Add these endpoints to your existing app.py
"""



# ==================== ADDITIONAL IMPORTS (Add to existing imports) ====================
# These should be added to your existing imports at the top of app.py

# ==================== ARTIST-SPECIFIC DIRECTORY SETUP ====================
ARTIST_CV_DIR = BASE_DIR / "artist_cvs"
ARTIST_CV_DIR.mkdir(exist_ok=True)

# ==================== DATABASE MODIFICATIONS ====================
# Add this to your init_db() function to ensure artist_applications table has all needed columns

def init_db_artist_extensions():
    """Extended database initialization for artist features"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if artist_applications table needs updates
    cursor.execute("PRAGMA table_info(artist_applications)")
    columns = {col[1] for col in cursor.fetchall()}
    
    # Add missing columns if needed
    if 'cv_url' not in columns:
        cursor.execute("ALTER TABLE artist_applications ADD COLUMN cv_url TEXT")
    if 'notes' not in columns:
        cursor.execute("ALTER TABLE artist_applications ADD COLUMN notes TEXT")
    if 'reviewed_at' not in columns:
        cursor.execute("ALTER TABLE artist_applications ADD COLUMN reviewed_at TIMESTAMP")
    
    conn.commit()
    conn.close()

# Call this after init_db() in your startup
# init_db_artist_extensions()

# ==================== ARTIST PROFILE & CV MANAGEMENT ====================

@app.post("/api/artists/upload-cv")
async def upload_artist_cv(
    file: UploadFile = File(...),
    artist_contact: str = Form(...)
):
    """Upload CV/Portfolio for artist profile"""
    try:
        # Validate file type
        if not file.filename.endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted for CV upload")
        
        # Create artist-specific directory
        artist_dir = ARTIST_CV_DIR / artist_contact.replace('+', '').replace(' ', '_')
        artist_dir.mkdir(parents=True, exist_ok=True)
        
        # Remove old CV if exists
        for old_file in artist_dir.glob('*.pdf'):
            old_file.unlink()
        
        # Save new CV
        filename = f"cv_{uuid.uuid4().hex[:8]}.pdf"
        file_path = artist_dir / filename
        
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        
        cv_url = f"/artist-cvs/{artist_contact.replace('+', '').replace(' ', '_')}/{filename}"
        
        return {
            "success": True,
            "url": cv_url,
            "message": "CV uploaded successfully"
        }
        
    except Exception as e:
        print(f"Error uploading CV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/artist-cvs/{artist_contact}/{filename}")
def get_artist_cv(artist_contact: str, filename: str):
    """Retrieve artist CV file"""
    file_path = ARTIST_CV_DIR / artist_contact / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CV not found")
    return FileResponse(file_path, media_type="application/pdf")


# ==================== EVENT DISCOVERY FOR ARTISTS ====================

@app.get("/api/artists/find-events")
def find_events_for_artists(
    city: Optional[str] = None,
    category: Optional[str] = None,
    skill_type: Optional[str] = None
):
    """
    Discover events that are actively looking for artists
    Filters by city, category, and skill type
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Base query - only active events needing artists
        query = """
            SELECT e.*, 
                   (SELECT COUNT(*) FROM artist_applications 
                    WHERE event_id = e.id AND status = 'approved') as filled_slots
            FROM events e
            WHERE e.need_artists = 1 
            AND e.status = 'active'
            AND e.date >= date('now')
        """
        params = []
        
        # Add filters
        if city:
            query += " AND e.city = ?"
            params.append(city)
        
        if category:
            query += " AND e.category = ?"
            params.append(category)
        
        # Order by date (upcoming first) and views (popular first)
        query += " ORDER BY e.date ASC, e.views DESC"
        
        cursor.execute(query, params)
        events = []
        
        for row in cursor.fetchall():
            event_dict = dict(row)
            filled_slots = event_dict.pop('filled_slots', 0)
            
            # Only include events with available slots
            if filled_slots < event_dict['artist_slots']:
                event_dict['available_slots'] = event_dict['artist_slots'] - filled_slots
                events.append(event_dict)
        
        conn.close()
        
        # Filter by skill_type recommendation if provided
        if skill_type:
            # Prioritize events matching skill type
            matching = [e for e in events if e['category'] == skill_type]
            other = [e for e in events if e['category'] != skill_type]
            events = matching + other
        
        return {"events": events, "count": len(events)}
        
    except Exception as e:
        print(f"Error finding events for artists: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/artists/recommended-events/{artist_contact}")
def get_recommended_events(artist_contact: str):
    """
    Get AI-powered event recommendations based on artist's application history
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get artist's past applications to understand preferences
        cursor.execute("""
            SELECT DISTINCT e.category, e.city 
            FROM artist_applications aa
            JOIN events e ON aa.event_id = e.id
            WHERE aa.artist_contact = ?
        """, (artist_contact,))
        
        history = cursor.fetchall()
        preferred_categories = list(set([h['category'] for h in history]))
        preferred_cities = list(set([h['city'] for h in history]))
        
        # Build recommendation query
        query = """
            SELECT e.*, 
                   (SELECT COUNT(*) FROM artist_applications 
                    WHERE event_id = e.id AND status = 'approved') as filled_slots
            FROM events e
            WHERE e.need_artists = 1 
            AND e.status = 'active'
            AND e.date >= date('now')
            AND e.id NOT IN (
                SELECT event_id FROM artist_applications 
                WHERE artist_contact = ?
            )
        """
        params = [artist_contact]
        
        # Prioritize based on history
        if preferred_categories:
            placeholders = ','.join(['?' for _ in preferred_categories])
            query += f" AND (e.category IN ({placeholders}) OR 1=1)"
            params.extend(preferred_categories)
        
        query += " ORDER BY e.date ASC LIMIT 10"
        
        cursor.execute(query, params)
        events = []
        
        for row in cursor.fetchall():
            event_dict = dict(row)
            filled_slots = event_dict.pop('filled_slots', 0)
            
            if filled_slots < event_dict['artist_slots']:
                event_dict['available_slots'] = event_dict['artist_slots'] - filled_slots
                event_dict['recommended_reason'] = (
                    "Matches your previous interests" if event_dict['category'] in preferred_categories 
                    else "Popular in your area" if event_dict['city'] in preferred_cities 
                    else "New opportunity"
                )
                events.append(event_dict)
        
        conn.close()
        
        return {"recommended_events": events}
        
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ARTIST APPLICATION MANAGEMENT ====================

@app.post("/api/artists/apply")
def submit_artist_application(application: ArtistApplication):
    """
    Submit artist application for an event (ENHANCED VERSION)
    Includes validation and conflict checking
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. Validate event exists and accepts artists
        cursor.execute("""
            SELECT need_artists, artist_slots, date, time, city
            FROM events WHERE id = ? AND status = 'active'
        """, (application.event_id,))
        event = cursor.fetchone()
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found or inactive")
        
        need_artists, artist_slots, event_date, event_time, event_city = event
        
        if not need_artists:
            raise HTTPException(status_code=400, detail="This event is not accepting artist applications")
        
        # 2. Check if already applied
        cursor.execute("""
            SELECT id, status FROM artist_applications 
            WHERE event_id = ? AND artist_contact = ?
        """, (application.event_id, application.artist_contact))
        existing = cursor.fetchone()
        
        if existing:
            status = existing[1]
            if status == 'pending':
                raise HTTPException(status_code=400, detail="You have already applied to this event. Application is under review.")
            elif status == 'approved':
                raise HTTPException(status_code=400, detail="You are already approved for this event!")
            elif status == 'rejected':
                raise HTTPException(status_code=400, detail="Your previous application was rejected. Please contact the organizer for reconsideration.")
        
        # 3. Check available slots
        cursor.execute("""
            SELECT COUNT(*) FROM artist_applications 
            WHERE event_id = ? AND status = 'approved'
        """, (application.event_id,))
        approved_count = cursor.fetchone()[0]
        
        if approved_count >= artist_slots:
            raise HTTPException(status_code=400, detail="All artist slots are filled for this event")
        
        # 4. Check for scheduling conflicts (same date/time in same city)
        cursor.execute("""
            SELECT e.title_en, e.date, e.time 
            FROM artist_applications aa
            JOIN events e ON aa.event_id = e.id
            WHERE aa.artist_contact = ?
            AND aa.status = 'approved'
            AND e.date = ?
            AND e.city = ?
        """, (application.artist_contact, event_date, event_city))
        conflicts = cursor.fetchall()
        
        if conflicts:
            conflict_details = ", ".join([f"{c[0]} at {c[2]}" for c in conflicts])
            raise HTTPException(
                status_code=400, 
                detail=f"Schedule conflict detected. You are already approved for: {conflict_details}"
            )
        
        # 5. Create application
        application_id = str(uuid.uuid4())
        
        cursor.execute("""
            INSERT INTO artist_applications (
                id, event_id, artist_name, artist_contact, 
                skill_type, experience, portfolio_url, status, cv_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            application_id,
            application.event_id,
            application.artist_name,
            application.artist_contact,
            application.skill_type,
            application.experience,
            application.portfolio_url,
            application.portfolio_url  # Using portfolio_url as cv_url for now
        ))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "application_id": application_id,
            "message": "Application submitted successfully! You will be notified once reviewed."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating artist application: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/artists/my-applications/{artist_contact}")
def get_my_applications(artist_contact: str):
    """
    Get all applications submitted by an artist with event details
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                aa.*,
                e.title_en,
                e.title_kn,
                e.category,
                e.date,
                e.time,
                e.city,
                e.venue,
                e.poster_url,
                e.organizer_name,
                e.organizer_contact,
                e.status as event_status
            FROM artist_applications aa
            JOIN events e ON aa.event_id = e.id
            WHERE aa.artist_contact = ?
            ORDER BY aa.applied_at DESC
        """, (artist_contact,))
        
        applications = []
        for row in cursor.fetchall():
            app_dict = dict(row)
            applications.append(app_dict)
        
        conn.close()
        
        # Group by status for better organization
        result = {
            "applications": applications,
            "summary": {
                "total": len(applications),
                "pending": len([a for a in applications if a['status'] == 'pending']),
                "approved": len([a for a in applications if a['status'] == 'approved']),
                "rejected": len([a for a in applications if a['status'] == 'rejected'])
            }
        }
        
        return result
        
    except Exception as e:
        print(f"Error fetching applications: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/artists/application-status/{event_id}/{artist_contact}")
def check_application_status(event_id: str, artist_contact: str):
    """
    Check if artist has applied to a specific event and get status
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT status, applied_at, reviewed_at, notes
            FROM artist_applications
            WHERE event_id = ? AND artist_contact = ?
        """, (event_id, artist_contact))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "applied": True,
                "status": result['status'],
                "applied_at": result['applied_at'],
                "reviewed_at": result['reviewed_at'],
                "notes": result['notes']
            }
        else:
            return {"applied": False, "status": "not_applied"}
        
    except Exception as e:
        print(f"Error checking application status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ORGANIZER-SIDE: ARTIST APPLICATION MANAGEMENT ====================

@app.get("/api/events/{event_id}/artist-applications")
def get_event_artist_applications(event_id: str):
    """
    Get all artist applications for a specific event (for organizers)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Verify event exists
        cursor.execute("SELECT id, organizer_contact FROM events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Get all applications
        cursor.execute("""
            SELECT * FROM artist_applications
            WHERE event_id = ?
            ORDER BY 
                CASE status
                    WHEN 'pending' THEN 1
                    WHEN 'approved' THEN 2
                    WHEN 'rejected' THEN 3
                END,
                applied_at DESC
        """, (event_id,))
        
        applications = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return {
            "applications": applications,
            "summary": {
                "total": len(applications),
                "pending": len([a for a in applications if a['status'] == 'pending']),
                "approved": len([a for a in applications if a['status'] == 'approved']),
                "rejected": len([a for a in applications if a['status'] == 'rejected'])
            }
        }
        
    except Exception as e:
        print(f"Error fetching artist applications: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/events/{event_id}/artist-applications/{application_id}/review")
def review_artist_application(
    event_id: str,
    application_id: str,
    action: str = Form(...),  # 'approve' or 'reject'
    notes: Optional[str] = Form(None)
):
    """
    Approve or reject an artist application (for organizers)
    """
    try:
        if action not in ['approve', 'reject']:
            raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Verify application exists
        cursor.execute("""
            SELECT aa.event_id, aa.status, e.artist_slots
            FROM artist_applications aa
            JOIN events e ON aa.event_id = e.id
            WHERE aa.id = ? AND aa.event_id = ?
        """, (application_id, event_id))
        
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Application not found")
        
        current_status = result[1]
        artist_slots = result[2]
        
        if current_status != 'pending':
            raise HTTPException(
                status_code=400, 
                detail=f"Application has already been {current_status}"
            )
        
        # If approving, check slot availability
        if action == 'approve':
            cursor.execute("""
                SELECT COUNT(*) FROM artist_applications
                WHERE event_id = ? AND status = 'approved'
            """, (event_id,))
            approved_count = cursor.fetchone()[0]
            
            if approved_count >= artist_slots:
                raise HTTPException(
                    status_code=400, 
                    detail="All artist slots are already filled"
                )
        
        # Update application status
        new_status = 'approved' if action == 'approve' else 'rejected'
        cursor.execute("""
            UPDATE artist_applications
            SET status = ?, reviewed_at = CURRENT_TIMESTAMP, notes = ?
            WHERE id = ?
        """, (new_status, notes, application_id))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "application_id": application_id,
            "new_status": new_status,
            "message": f"Application {new_status} successfully"
        }
        
    except Exception as e:
        print(f"Error reviewing application: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ARTIST ANALYTICS & INSIGHTS ====================

@app.get("/api/artists/analytics/{artist_contact}")
def get_artist_analytics(artist_contact: str):
    """
    Get analytics and insights for an artist's application history
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Overall stats
        cursor.execute("""
            SELECT 
                COUNT(*) as total_applications,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
            FROM artist_applications
            WHERE artist_contact = ?
        """, (artist_contact,))
        
        stats = dict(cursor.fetchone())
        
        # Success rate
        if stats['total_applications'] > 0:
            stats['success_rate'] = round(
                (stats['approved'] / stats['total_applications']) * 100, 1
            )
        else:
            stats['success_rate'] = 0
        
        # Category breakdown
        cursor.execute("""
            SELECT e.category, COUNT(*) as count,
                   SUM(CASE WHEN aa.status = 'approved' THEN 1 ELSE 0 END) as approved
            FROM artist_applications aa
            JOIN events e ON aa.event_id = e.id
            WHERE aa.artist_contact = ?
            GROUP BY e.category
        """, (artist_contact,))
        
        category_stats = [dict(row) for row in cursor.fetchall()]
        
        # Upcoming approved events
        cursor.execute("""
            SELECT e.title_en, e.date, e.time, e.city, e.venue
            FROM artist_applications aa
            JOIN events e ON aa.event_id = e.id
            WHERE aa.artist_contact = ?
            AND aa.status = 'approved'
            AND e.date >= date('now')
            ORDER BY e.date ASC
        """, (artist_contact,))
        
        upcoming_events = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "overall_stats": stats,
            "category_breakdown": category_stats,
            "upcoming_performances": upcoming_events
        }
        
    except Exception as e:
        print(f"Error fetching artist analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SEARCH & FILTER UTILITIES ====================

@app.get("/api/artists/search-events")
def search_events_for_artists(
    query: str,
    city: Optional[str] = None,
    category: Optional[str] = None,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None
):
    """
    Advanced search for events with multiple filters
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        sql_query = """
            SELECT e.*, 
                   (SELECT COUNT(*) FROM artist_applications 
                    WHERE event_id = e.id AND status = 'approved') as filled_slots
            FROM events e
            WHERE e.need_artists = 1 
            AND e.status = 'active'
            AND e.date >= date('now')
            AND (
                e.title_en LIKE ? OR
                e.description LIKE ? OR
                e.venue LIKE ?
            )
        """
        
        search_param = f"%{query}%"
        params = [search_param, search_param, search_param]
        
        if city:
            sql_query += " AND e.city = ?"
            params.append(city)
        
        if category:
            sql_query += " AND e.category = ?"
            params.append(category)
        
        if min_date:
            sql_query += " AND e.date >= ?"
            params.append(min_date)
        
        if max_date:
            sql_query += " AND e.date <= ?"
            params.append(max_date)
        
        sql_query += " ORDER BY e.date ASC"
        
        cursor.execute(sql_query, params)
        
        events = []
        for row in cursor.fetchall():
            event_dict = dict(row)
            filled_slots = event_dict.pop('filled_slots', 0)
            
            if filled_slots < event_dict['artist_slots']:
                event_dict['available_slots'] = event_dict['artist_slots'] - filled_slots
                events.append(event_dict)
        
        conn.close()
        
        return {"events": events, "count": len(events)}
        
    except Exception as e:
        print(f"Error searching events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== NOTIFICATION HELPERS (Optional Enhancement) ====================

def notify_artist_status_change(artist_contact: str, event_title: str, status: str):
    """
    Helper function to send notifications when application status changes
    Can be integrated with SMS/Email services
    """
    # Placeholder for future notification integration
    print(f"[NOTIFICATION] Artist {artist_contact}: Application for '{event_title}' is now {status}")
    
    # TODO: Integrate with SMS API (Twilio) or Email service
    # Example:
    # if status == 'approved':
    #     send_sms(artist_contact, f"Congratulations! You're approved for {event_title}")
    pass


# ==================== STARTUP LOGGING ====================

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("🎨 Namma Karnataka - Artist Features Enabled")
    print("="*50)
    print(f"📁 Artist CV Directory: {ARTIST_CV_DIR}")
    print("="*50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)