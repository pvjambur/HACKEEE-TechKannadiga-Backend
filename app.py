"""
Namma Karnataka - Event Management Backend
Complete working implementation with AI poster generation and LLM Chat/Data Augmentation
"""

import os
import uuid
import json
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from io import BytesIO

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ✅ Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv() 

# ✅ LLM/AI IMPORTS
from google import genai
from google.genai import types
from PIL import Image
from groq import Groq # New Groq Import

# Initialize FastAPI app
app = FastAPI(title="Namma Karnataka API")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory setup
BASE_DIR = Path(__file__).parent
POSTERS_DIR = BASE_DIR / "posters"
VIDEOS_DIR = BASE_DIR / "videos"
DB_PATH = BASE_DIR / "events.db"

POSTERS_DIR.mkdir(exist_ok=True)
VIDEOS_DIR.mkdir(exist_ok=True)

# ==================== DATABASE SETUP ====================

def init_db():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Events table (MODIFIED: Added fake_views_and_likes column)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title_en TEXT NOT NULL,
            title_kn TEXT,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            city TEXT NOT NULL,
            venue TEXT NOT NULL,
            price REAL NOT NULL,
            capacity INTEGER NOT NULL,
            need_artists BOOLEAN DEFAULT 0,
            artist_slots INTEGER DEFAULT 0,
            organizer_name TEXT NOT NULL,
            organizer_contact TEXT NOT NULL,
            poster_url TEXT,
            video_url TEXT,
            status TEXT DEFAULT 'active',
            views INTEGER DEFAULT 0,
            bookings INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT,
            fake_views_and_likes TEXT DEFAULT '{"initial_views": 0, "initial_likes": 0}' 
        )
    """)
    
    # Interactions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            interaction_type TEXT NOT NULL,
            user_name TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)
    
    # Bookings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            user_name TEXT NOT NULL,
            user_contact TEXT NOT NULL,
            tickets INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)
    
    # Artist applications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS artist_applications (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            artist_contact TEXT NOT NULL,
            skill_type TEXT NOT NULL,
            experience TEXT,
            portfolio_url TEXT,
            status TEXT DEFAULT 'pending',
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# ==================== PYDANTIC MODELS (No change) ====================

class EventCreate(BaseModel):
    title_en: str
    title_kn: Optional[str] = None
    description: str
    category: str
    date: str
    time: str
    city: str
    venue: str
    price: float
    capacity: int
    need_artists: bool = False
    artist_slots: int = 0
    organizer_name: str
    organizer_contact: str

class InteractionCreate(BaseModel):
    event_id: str
    interaction_type: str
    user_name: Optional[str] = None
    message: str

class BookingCreate(BaseModel):
    event_id: str
    user_name: str
    user_contact: str
    tickets: int

class ArtistApplication(BaseModel):
    event_id: str
    artist_name: str
    artist_contact: str
    skill_type: str
    experience: Optional[str] = None
    portfolio_url: Optional[str] = None

# ==================== LLM AUGMENTATION FUNCTIONS (NEW/MODIFIED) ====================

# Helper function to get Groq client
def get_groq_client():
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        print("⚠️ Groq API key not configured. Skipping LLM data generation/chat.")
        return None
    return Groq(api_key=api_key)

def generate_llm_metadata(event: EventCreate) -> str:
    """Use Groq to generate enhanced metadata (highlights, audience, duration)"""
    client = get_groq_client()
    if not client:
        return json.dumps({
            "highlights": [f"Standard {event.category} event", f"Located in {event.city}"],
            "target_audience": "Culture enthusiasts and families",
            "suggested_duration": "2 hours"
        })

    prompt = f"""
    Analyze the following event details and generate a JSON object with marketing metadata.
    Event Title: {event.title_en}
    Event Description: {event.description}
    Category: {event.category}
    City: {event.city}
    
    The output MUST be a JSON object with the following structure:
    {{
      "highlights": ["3 key selling points or highlights in English, marketing-focused"],
      "target_audience": "Describe the ideal target audience in one English phrase (e.g., Families, Young Professionals, Classical Music Lovers)",
      "suggested_duration": "Provide a suggested duration in one English phrase (e.g., 3 hours, Full Day, Evening Gala)"
    }}
    Ensure the tone is culturally appropriate for Karnataka and enthusiastic.
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant", # Groq's fast and capable model
            response_format={"type": "json_object"}
        )
        metadata_json_str = chat_completion.choices[0].message.content
        # Validate and return JSON string
        json.loads(metadata_json_str) # Quick validation
        return metadata_json_str
    except Exception as e:
        print(f"❌ Groq Metadata Generation Error: {e}. Returning default metadata.")
        return json.dumps({
            "highlights": [f"Culturally rich {event.category} experience", f"Centrally located in {event.city}", "Powered by Namma Karnataka Events"],
            "target_audience": "All enthusiasts of Karnataka culture",
            "suggested_duration": "Flexible"
        })

def generate_llm_statistics(event_id: str, event_title: str) -> dict:
    """Use Groq to generate fake starting engagement data (views, likes)"""
    client = get_groq_client()
    if not client:
        return {"initial_views": 10, "initial_likes": 5} # Default low engagement

    prompt = f"""
    Based on the average success of a cultural event in Karnataka with the title: '{event_title}',
    and assuming this is a brand new event listing, generate a JSON object representing initial,
    slightly padded engagement numbers to make the post look more appealing.
    
    The output MUST be a JSON object with the following structure and values within realistic ranges:
    {{
      "initial_views": <integer, between 50 and 300>,
      "initial_likes": <integer, between 10 and 50>
    }}
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        stats_data = json.loads(chat_completion.choices[0].message.content)
        
        # Enforce integer and default values
        views = int(stats_data.get("initial_views", 100))
        likes = int(stats_data.get("initial_likes", 20))
        
        print(f"📊 Generated Initial Stats: Views={views}, Likes={likes}")
        return {"initial_views": views, "initial_likes": likes}
        
    except Exception as e:
        print(f"❌ Groq Stats Generation Error: {e}. Returning default stats.")
        return {"initial_views": 100, "initial_likes": 20}

# ==================== GEMINI POSTER GENERATION (Slightly simplified for brevity but core logic retained) ====================

def generate_event_poster(event_id: str, event_title: str, category: str, city: str) -> Optional[str]:
    """
    Generate a poster dynamically using Gemini API and save to disk.
    (Original logic retained)
    """
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("⚠️ Gemini API key not configured. Skipping image generation.")
        return None
    
    try:
        client = genai.Client(api_key=api_key)
        
        prompt = (
            f"Generate an eye-catching event poster for a cultural event in a vibrant, "
            f"traditional art style of Karnataka. "
            f"Event Title: '{event_title}'. Category: {category}. Location: {city}. "
            f"Concept: Visually represent the core theme of the event, focusing on cultural "
            f"elements like traditional music instruments, or local architecture "
            f"related to the category. The image should be vibrant and suitable for a digital "
            f"event flyer. Ensure the City name is on the poster."
        )
        
        print(f"📝 Generating AI poster for: {event_title}")
        
        # Using models.generate_images for dedicated image generation, if available, otherwise fallback.
        # The user's code used a deprecated call, keeping the structure as close as possible
        # while addressing the prompt's explicit Gemini requirement.
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'])
        )
        
        if not response or not response.candidates:
            print("❌ No candidates received from Gemini API.")
            return None
        
        image_part = next((part for part in response.candidates[0].content.parts if part.inline_data), None)

        if image_part:
            poster_dir = POSTERS_DIR / event_id
            shutil.rmtree(poster_dir, ignore_errors=True)
            poster_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"ai_poster_{uuid.uuid4().hex[:8]}.png" 
            file_path = poster_dir / filename
            
            image = Image.open(BytesIO(image_part.inline_data.data))
            image.save(str(file_path), format='PNG')
            
            poster_url = f"/posters/{event_id}/{filename}"
            return poster_url
        
        print("❌ No image data found in response.")
        return None
        
    except Exception as e:
        print(f"❌ Gemini Image Generation Error: {e}")
        return None


# ==================== API ENDPOINTS (MODIFIED) ====================

@app.get("/")
def read_root():
    return {"message": "Namma Karnataka API", "status": "running"}

@app.get("/posters/{event_id}/{filename}")
def get_poster(event_id: str, filename: str):
    file_path = POSTERS_DIR / event_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Poster not found")
    return FileResponse(file_path)

@app.get("/videos/{event_id}/{filename}")
def get_video(event_id: str, filename: str):
    file_path = VIDEOS_DIR / event_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(file_path)

@app.get("/api/cities")
def get_cities():
    cities = [
        "Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi",
        "Davanagere", "Ballari", "Tumakuru", "Shivamogga", "Vijayapura"
    ]
    return {"cities": cities}

@app.get("/api/venues/{city}")
def get_venues(city: str):
    venues_map = {
        "Bengaluru": ["Chowdiah Memorial Hall", "Ravindra Kalakshetra", "Rangashankara"],
        "Mysuru": ["Kalamandira", "Jaganmohan Palace", "Mysore Palace Grounds"],
        "Hubballi": ["Town Hall", "Karnatak College Grounds", "Kittur Rani Chennamma Stadium"],
        "Mangaluru": ["Town Hall", "Mangala Stadium", "Kadri Park"],
        "Belagavi": ["Suvarna Vidhana Soudha Grounds", "Military Maidan", "District Stadium"]
    }
    venues = venues_map.get(city, ["City Hall", "Community Center", "Public Grounds"])
    return {"venues": venues}

@app.post("/api/events/create")
async def create_event(event: EventCreate):
    """Create a new event with AI poster generation and LLM data augmentation (MODIFIED)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        event_id = str(uuid.uuid4())
        
        # 1. Generate AI poster (Gemini)
        poster_url = generate_event_poster(
            event_id=event_id,
            event_title=event.title_en,
            category=event.category,
            city=event.city
        )
        
        # 2. Generate enhanced metadata (Groq)
        metadata_json_str = generate_llm_metadata(event)
        
        # 3. Generate initial statistics (Groq)
        stats_dict = generate_llm_statistics(event_id, event.title_en)
        fake_stats_json_str = json.dumps(stats_dict)
        
        # 4. Insert event (MODIFIED: Added fake_views_and_likes)
        cursor.execute("""
            INSERT INTO events (
                id, title_en, title_kn, description, category, date, time,
                city, venue, price, capacity, need_artists, artist_slots,
                organizer_name, organizer_contact, poster_url, metadata, status, fake_views_and_likes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id, event.title_en, event.title_kn, event.description,
            event.category, event.date, event.time, event.city, event.venue,
            event.price, event.capacity, event.need_artists, event.artist_slots,
            event.organizer_name, event.organizer_contact, poster_url,
            metadata_json_str, 'active', fake_stats_json_str
        ))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "event_id": event_id,
            "message": "Event created successfully with AI augmentation",
            "event": {
                "id": event_id,
                "title": event.title_en,
                "poster_url": poster_url,
                "metadata": metadata_json_str
            }
        }
        
    except Exception as e:
        print(f"Error creating event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/{event_id}/upload-media")
async def upload_media(
    event_id: str,
    file: UploadFile = File(...),
    media_type: str = Form(...)
):
    """Upload poster or video for an event (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM events WHERE id = ?", (event_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Event not found")
        
        if media_type == "poster":
            # Clean up folder to remove AI generated or old manual poster
            shutil.rmtree(POSTERS_DIR / event_id, ignore_errors=True) 
            media_dir = POSTERS_DIR / event_id
            media_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"manual_poster_{uuid.uuid4().hex[:8]}.{file.filename.split('.')[-1]}"
            file_path = media_dir / filename
            
            contents = await file.read()
            with open(file_path, "wb") as f:
                f.write(contents)
            
            media_url = f"/posters/{event_id}/{filename}"
            cursor.execute("UPDATE events SET poster_url = ? WHERE id = ?", (media_url, event_id))
            
        elif media_type == "video":
            # Clean up video folder
            shutil.rmtree(VIDEOS_DIR / event_id, ignore_errors=True) 
            media_dir = VIDEOS_DIR / event_id
            media_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"video_{uuid.uuid4().hex[:8]}.{file.filename.split('.')[-1]}" 
            file_path = media_dir / filename
            
            contents = await file.read()
            with open(file_path, "wb") as f:
                f.write(contents)
            
            media_url = f"/videos/{event_id}/{filename}"
            cursor.execute("UPDATE events SET video_url = ? WHERE id = ?", (media_url, event_id))
        else:
            raise HTTPException(status_code=400, detail="Invalid media type")
        
        conn.commit()
        conn.close()
        
        return {"success": True, "url": media_url}
        
    except Exception as e:
        print(f"Error uploading media: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/my-events/{organizer_contact}")
def get_my_events(organizer_contact: str):
    """Get all events by organizer contact (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM events 
            WHERE organizer_contact = ? 
            ORDER BY created_at DESC
        """, (organizer_contact,))
        
        events = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return {"events": events}
        
    except Exception as e:
        print(f"Error fetching events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/{event_id}/stats")
def get_event_stats(event_id: str):
    """Get statistics for an event (MODIFIED to include fake stats)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get event data
        cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Parse fake stats
        fake_stats = json.loads(event["fake_views_and_likes"])
        
        # Get bookings count
        cursor.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(tickets), 0) as tickets_sold
            FROM bookings WHERE event_id = ?
        """, (event_id,))
        booking_data = cursor.fetchone()
        
        # Get artist applications count
        cursor.execute("""
            SELECT COUNT(*) as total FROM artist_applications WHERE event_id = ?
        """, (event_id,))
        artist_data = cursor.fetchone()
        
        # Get interactions count
        cursor.execute("""
            SELECT COUNT(*) as total FROM interactions WHERE event_id = ?
        """, (event_id,))
        interaction_data = cursor.fetchone()
        
        conn.close()
        
        return {
            "event_id": event_id,
            # Add initial views from LLM for a better display
            "views": event["views"] + fake_stats.get("initial_views", 0), 
            "likes": fake_stats.get("initial_likes", 0), # Added explicit likes count
            "total_bookings": booking_data["total"],
            "tickets_sold": booking_data["tickets_sold"],
            "revenue": booking_data["tickets_sold"] * event["price"],
            "capacity": event["capacity"],
            "artist_applications": artist_data["total"],
            "interactions": interaction_data["total"],
            "status": event["status"]
        }
        
    except Exception as e:
        print(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/{event_id}/interactions")
def get_event_interactions(event_id: str):
    """Get all interactions for an event (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM interactions 
            WHERE event_id = ? 
            ORDER BY created_at DESC
        """, (event_id,))
        
        interactions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return {"interactions": interactions}
        
    except Exception as e:
        print(f"Error fetching interactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/{event_id}/interact")
def create_interaction(interaction: InteractionCreate):
    """Create a new interaction (comment, feedback, etc.) (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        interaction_id = str(uuid.uuid4())
        
        cursor.execute("""
            INSERT INTO interactions (id, event_id, interaction_type, user_name, message)
            VALUES (?, ?, ?, ?, ?)
        """, (
            interaction_id,
            interaction.event_id,
            interaction.interaction_type,
            interaction.user_name,
            interaction.message
        ))
        
        conn.commit()
        conn.close()
        
        return {"success": True, "interaction_id": interaction_id}
        
    except Exception as e:
        print(f"Error creating interaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bookings/create")
def create_booking(booking: BookingCreate):
    """Create a new booking (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check event availability
        cursor.execute("""
            SELECT capacity, bookings, price FROM events WHERE id = ?
        """, (booking.event_id,))
        event = cursor.fetchone()
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        capacity, current_bookings, price = event
        
        # Get tickets sold (re-calculate in case event table 'bookings' is stale)
        cursor.execute("""
            SELECT COALESCE(SUM(tickets), 0) FROM bookings WHERE event_id = ?
        """, (booking.event_id,))
        tickets_sold = cursor.fetchone()[0]
        
        if tickets_sold + booking.tickets > capacity:
            raise HTTPException(status_code=400, detail="Not enough tickets available")
        
        # Create booking
        booking_id = str(uuid.uuid4())
        total_amount = booking.tickets * price
        
        cursor.execute("""
            INSERT INTO bookings (id, event_id, user_name, user_contact, tickets, total_amount)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            booking_id,
            booking.event_id,
            booking.user_name,
            booking.user_contact,
            booking.tickets,
            total_amount
        ))
        
        # Update event bookings count (increment by 1 for total bookings)
        cursor.execute("""
            UPDATE events SET bookings = bookings + 1 WHERE id = ?
        """, (booking.event_id,))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "booking_id": booking_id,
            "total_amount": total_amount
        }
        
    except Exception as e:
        print(f"Error creating booking: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/artists/apply")
def apply_as_artist(application: ArtistApplication):
    """Submit artist application for an event (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if event accepts artists
        cursor.execute("""
            SELECT need_artists, artist_slots FROM events WHERE id = ?
        """, (application.event_id,))
        event = cursor.fetchone()
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        need_artists, artist_slots = event
        
        if not need_artists:
            raise HTTPException(status_code=400, detail="Event is not accepting artists")
        
        # Check available slots
        cursor.execute("""
            SELECT COUNT(*) FROM artist_applications 
            WHERE event_id = ? AND status = 'approved'
        """, (application.event_id,))
        approved_count = cursor.fetchone()[0]
        
        if approved_count >= artist_slots:
            raise HTTPException(status_code=400, detail="No artist slots available")
        
        # Create application
        application_id = str(uuid.uuid4())
        
        cursor.execute("""
            INSERT INTO artist_applications (
                id, event_id, artist_name, artist_contact, 
                skill_type, experience, portfolio_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            application_id,
            application.event_id,
            application.artist_name,
            application.artist_contact,
            application.skill_type,
            application.experience,
            application.portfolio_url
        ))
        
        conn.commit()
        conn.close()
        
        return {"success": True, "application_id": application_id}
        
    except Exception as e:
        print(f"Error creating artist application: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/{event_id}/download-report")
def download_report(event_id: str):
    """Generate and download event report (NO CHANGE to logic)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get event details
        cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Get stats (Using get_event_stats logic for report consistency)
        stats = get_event_stats(event_id)
        
        conn.close()
        
        # Generate report text
        report = f"""
EVENT REPORT
============

Event: {event['title_en']}
Category: {event['category']}
Date: {event['date']} at {event['time']}
Location: {event['venue']}, {event['city']}

STATISTICS
----------
Views (Augmented): {stats['views']}
Likes (Augmented): {stats['likes']}
Total Bookings: {stats['total_bookings']}
Tickets Sold: {stats['tickets_sold']} / {event['capacity']}
Revenue: ₹{stats['revenue']}

Status: {event['status']}
Created: {event['created_at']}

ORGANIZER
---------
Name: {event['organizer_name']}
Contact: {event['organizer_contact']}
"""
        
        # Save report to file
        report_path = BASE_DIR / f"event_report_{event_id}.txt"
        with open(report_path, "w") as f:
            f.write(report)
        
        return FileResponse(
            report_path,
            media_type="text/plain",
            filename=f"event_report_{event_id}.txt"
        )
        
    except Exception as e:
        print(f"Error generating report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_with_ai(request: dict):
    """LLM Chat endpoint using Groq with optional event context (MODIFIED)"""
    client = get_groq_client()
    if not client:
        return {"response": "AI Assistant is currently unavailable. Please check the GROQ_API_KEY environment variable."}
    
    message = request.get("message", "")
    event_id = request.get("event_id")
    
    system_prompt = (
        "You are the Namma Karnataka Event Management Assistant. Your role is to assist the event organizer "
        "with event creation, promotion, management questions, and cultural advice, using a helpful and "
        "respectful tone (bilingual English/Kannada is a plus)."
    )
    
    context = ""
    if event_id:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT title_en, description, category, date, city, capacity, price FROM events WHERE id = ?", (event_id,))
            event = cursor.fetchone()
            
            if event:
                context = (
                    f"Event Context: [Title: {event['title_en']}, Description: {event['description'][:100]}..., "
                    f"Category: {event['category']}, Date: {event['date']}, Location: {event['city']}, "
                    f"Price: {event['price']}, Capacity: {event['capacity']}]"
                )
            conn.close()
        except Exception as e:
            print(f"Error fetching event context for chat: {e}")
    
    full_prompt = f"{system_prompt}\n{context}\nUser Query: {message}"
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt + (" Focus your response on the provided event context." if event_id else "")},
                {"role": "user", "content": message + (f"\n\nContext for this question: {context}" if event_id else "")}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.7
        )
        
        response_text = chat_completion.choices[0].message.content
        
        return {"response": response_text}
        
    except Exception as e:
        print(f"Error in Groq chat: {e}")
        return {"response": "ಕ್ಷಮಿಸಿ, AI ಸಹಾಯಕವು ಪ್ರಸ್ತುತ ತಾಂತ್ರಿಕ ದೋಷವನ್ನು ಎದುರಿಸುತ್ತಿದೆ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ. (Sorry, the AI assistant is currently experiencing a technical error. Please try again later.)"}
    
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

# ==================== RUN SERVER ====================

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("🎉 Namma Karnataka Backend Starting...")
    print("="*50)
    print(f"📁 Database: {DB_PATH}")
    print(f"📁 Posters: {POSTERS_DIR}")
    print(f"📁 Videos: {VIDEOS_DIR}")
    print(f"🔑 Gemini API: {'✅ Configured' if os.environ.get('GEMINI_API_KEY') else '❌ Not configured'}")
    print(f"🔑 Groq API: {'✅ Configured' if os.environ.get('GROQ_API_KEY') else '❌ Not configured (Chat/Data Augmentation disabled)'}")
    print("="*50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)