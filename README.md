# TalentGraph

## What I made

I made this project to take information about people from three different CSV files, clean the information, find people who are the same person, and save the final information in one SQLite database.

I also added an audio collection part because the project is meant to show how this type of data system could be used for gig workers. A worker can enter their name and phone number, upload an audio recording, and submit it. The application stores the audio and saves useful audio information in the SQL database.

I also created an n8n workflow file for a no-code duplicate-check automation.

The complete idea is:

**3 CSV files → clean the data → find duplicates → combine the information → save it in SQL → search the people → collect audio → save audio details → automate duplicate checking with n8n.**

---

# What this project satisfies

My project is built around the five tasks in the assignment.

### Task 1 — Merge the three files

I use Python and SQLite to read all three CSV files and put the information into one clean database.

The same person can appear in more than one file. I do not use one common ID because the three files do not have one common ID. Instead, my program compares information such as:

- Email
- Phone number
- Name
- City

I normalize the values first and then use exact and fuzzy matching rules. When I can safely identify the same person, the records are connected to one person in the `users` table.

If the information conflicts and the program cannot safely prove that it is the same person, I do not force a merge. I record the problem as a data-quality issue.

### Task 2 — n8n automation

I created a real n8n workflow template named:

```text
n8n_talentgraph_duplicate_alert.json
```

The workflow is designed to:

```text
Receive a new person
       ↓
Normalize the input
       ↓
Check TalentGraph database
       ↓
Is a duplicate found?
       ↓
Yes → return duplicate alert
No  → return new-person result
```

This is intentionally an n8n workflow instead of only Python code because the assignment requires a no-code/low-code automation tool.

I still need to import the JSON into my n8n account, configure the SQLite database connection, run the workflow, and show it working in my demo video. The JSON file is included in the repository so the evaluator can inspect and import it.

### Task 3 — Mini audio collection app

My local dashboard now includes an audio collection form.

A worker can enter:

- Name
- Phone number
- Audio file

Then the worker clicks **Submit Audio**.

The application stores the audio in:

```text
audio_uploads/
```

and saves the submission in the SQLite table:

```text
audio_submissions
```

For every uploaded audio file, the application tries to store:

- Duration
- Sample rate in kHz
- Bitrate
- Loudness
- Rough quality estimate
- File size
- Original filename
- Stored filename
- Submission time

The dashboard also has an **Audio Submissions** section where I can see the submitted recordings and use a play button to listen to them.

For WAV files, the project has a Python standard-library fallback for basic audio metadata. For formats such as MP3 and M4A, the project can use `ffprobe`/`ffmpeg` when those tools are installed. If they are not installed, the application does not crash just because some metadata cannot be extracted; the unavailable values are shown as unknown.

The application has a 25 MB upload limit and supports these common formats:

```text
.wav
.mp3
.m4a
.aac
.ogg
.webm
.flac
```

### Task 4 — Data quality report

I created:

```text
DATA_QUALITY_REPORT.md
```

My Python pipeline also stores data-quality issues in:

```text
data_quality_issues
```

The checks cover problems such as:

- Blank rows
- Missing or invalid email addresses
- Invalid phone numbers
- Repeated CBNexus headers
- Corrupted gig-worker rows
- Invalid dates
- Invalid CTC values
- Invalid experience values
- Invalid gig-worker status values
- Invalid verification values
- Invalid project counts
- Conflicting identifiers
- Fuzzy matches that need lower-confidence treatment

The report explains how these problems are detected and what the program does with them.

### Task 5 — Planning for 5,000 workers

I created:

```text
STRETCH.md
```

This explains what I think would break first if thousands of gig workers used the application at the same time and what I would change before a real launch.

The main changes I would make are:

- Move audio files from local disk to object storage such as S3-compatible storage.
- Move from SQLite to PostgreSQL for production concurrency.
- Use direct/signed uploads instead of sending large files through the application server.
- Process audio asynchronously with a queue and workers.
- Add duplicate protection using file hashes and idempotency keys.
- Add upload limits and validation.
- Add authentication and rate limiting.
- Add retries and failure handling.
- Add monitoring and alerts.
- Add database backups and storage-retention rules.
- Load-test the system before a large launch.

---

# What are the three CSV files?

My project uses three input files:

```text
source1_naukri_applicants.csv
source2_gig_workers.csv
source3_cbnexus_contacts.csv
```

The files contain information about people, but the information is not always written in exactly the same way.

For example, the same phone number might be written in different formats. A person's name or email can also have different capitalization or formatting.

Because of this, I cannot simply put all three files together. First, I need to clean and compare the data.

---

# Project folder

My project looks like this:

```text
talentgraph/
│
├── data/
│   ├── source1_naukri_applicants.csv
│   ├── source2_gig_workers.csv
│   └── source3_cbnexus_contacts.csv
│
├── db/
│   ├── users.db
│   └── audio_uploads/
│
├── .vscode/
│   ├── launch.json
│   └── settings.json
│
├── merge_users.py
├── requirements.txt
├── n8n_talentgraph_duplicate_alert.json
├── DATA_QUALITY_REPORT.md
├── STRETCH.md
└── README.md
```

### What each part does

**`data/`**

This folder contains my three original CSV files. These are the files that my Python program reads.

**`db/`**

This folder contains my SQLite database and the audio-upload storage used by the local application.

**`users.db`**

This is the SQLite database created by the Python program.

**`audio_uploads/`**

This is where uploaded audio files are stored when I run the project locally.

**`merge_users.py`**

This is the main Python file. When I run it, it reads the CSV files, cleans the information, checks for duplicates, creates/updates the database, creates the n8n workflow/report files when needed, and opens the local dashboard.

**`requirements.txt`**

This contains the Python packages needed for the project.

**`n8n_talentgraph_duplicate_alert.json`**

This is the exported n8n workflow for the duplicate-check automation.

**`DATA_QUALITY_REPORT.md`**

This explains the data-quality problems checked by my pipeline and how I handle them.

**`STRETCH.md`**

This is my plan for scaling the audio application to thousands of workers.

**`.vscode/`**

These files help me run the project easily from Visual Studio Code.

---

# How I set up the project

I am using Python for this project.

First, I open Terminal and go to my project folder.

```bash
cd /Users/nishisingh/Downloads/talentgraph
```

If the project is in a different folder on another computer, I would use that folder's path instead.

Then I create a Python virtual environment:

```bash
python3 -m venv venv
```

A virtual environment gives my project its own place to install Python packages without changing the rest of my computer.

Then I activate it:

```bash
source venv/bin/activate
```

After activation, I should see something like:

```text
(venv) nishisingh@Nishis-MacBook-Air talentgraph %
```

Then I install the required packages:

```bash
python3 -m pip install -r requirements.txt
```

I use `python3 -m pip` because some Macs do not have a command called `python`.

---

# Optional: install FFmpeg for better audio metadata

The project can work with WAV metadata using Python's standard library.

For better support for MP3, M4A, AAC, OGG, WEBM and FLAC files, I recommend installing FFmpeg.

On macOS with Homebrew:

```bash
brew install ffmpeg
```

Then check it:

```bash
ffprobe -version
ffmpeg -version
```

FFmpeg is an external system tool, not a Python package, so it is not placed in `requirements.txt`.

If I do not have FFmpeg, I can still run the dashboard and upload WAV files.

---

# How my code works

The main file is:

```text
merge_users.py
```

When I run it, the program follows these steps:

```text
Start program
     ↓
Read the 3 CSV files
     ↓
Check the data
     ↓
Clean names, emails and phone numbers
     ↓
Look for people who are the same
     ↓
Match records carefully
     ↓
Create/update SQLite database
     ↓
Save the cleaned information
     ↓
Create n8n/report support files
     ↓
Open my local dashboard
```

Inside the dashboard I can also:

```text
Enter worker name + phone + audio
              ↓
         Upload audio
              ↓
       Store the audio file
              ↓
       Extract audio metadata
              ↓
       Save metadata in SQL
              ↓
      Show it in Audio Submissions
```

---

# How I run the program

## Option 1 — Run from Terminal

First activate my virtual environment:

```bash
source venv/bin/activate
```

Then run:

```bash
python3 merge_users.py
```

If I want to provide the files manually, I can also run:

```bash
python3 merge_users.py \
    --naukri data/source1_naukri_applicants.csv \
    --gig data/source2_gig_workers.csv \
    --cbnexus data/source3_cbnexus_contacts.csv \
    --db db/users.db
```

The first command is easier because my project already knows the default CSV filenames.

---

# Option 2 — Run from VS Code

I can also open the project in Visual Studio Code.

Then I open:

```text
merge_users.py
```

and click the **Run** button.

The program starts running and processes my CSV files.

After the database is created, the local dashboard opens in my browser.

---

# What happens when I run it?

When I run `merge_users.py`, the program first reads my three CSV files.

Then it tries to make the information easier to compare.

For example, phone numbers can be written in different ways. My code normalizes them so the program can compare them more easily.

The program also checks names and email addresses when trying to decide whether two records belong to the same person.

It does **not** simply merge everyone with the same name. This is important because two different people can have the same name.

After matching the records, the program creates one main person record and keeps the information that came from the different sources.

Finally, it saves everything in:

```text
db/users.db
```

---

# My SQL database

I use SQLite for the database.

SQLite is useful here because I can keep the whole database in one file:

```text
db/users.db
```

I do not need to install a separate database server just to run this project.

My database contains tables such as:

### `users`

This is the main table. It contains one record for each person that my program identifies.

It stores things such as the person's name, main email, main phone number, city, sources and match confidence.

### `user_emails`

This keeps email addresses found for each person.

### `user_phones`

This keeps phone numbers found for each person.

### `user_skills`

This keeps skills found for each person.

### `naukri_applications`

This keeps information that came from the Naukri source file.

### `gig_worker_profiles`

This keeps information that came from the gig-worker source file.

### `cbnexus_contacts`

This keeps information that came from the CBNexus source file.

### `data_quality_issues`

This keeps problems found while processing the data.

### `audio_submissions`

This keeps each audio submission and its extracted properties, such as duration, sample rate, bitrate, loudness and quality estimate.

---

# How I search for one person

After I run the Python file, my local dashboard opens in the browser.

I can use the **Search a Person** box.

I can search using:

- Name
- City
- Email
- Phone/contact number
- Skill
- Source

For example, I can type:

```text
Arjun Mehta
```

or:

```text
Delhi
```

If I search for a city, the dashboard shows **all people matching that city**, not only the first person.

If more than one person matches my search, I get a list of matching people. I can select one person and view the full details.

The dashboard can show:

- Name
- Email
- Phone
- City
- Sources
- Match confidence
- Number of source records
- Naukri information
- Gig-worker information
- CBNexus information
- Skills

---

# How I collect audio

In the dashboard, I go to **Audio Collection**.

I enter:

```text
Name
Phone
Audio file
```

Then I click:

```text
Submit Audio
```

The application saves the recording with a unique filename so two uploads do not overwrite each other.

The application also tries to find the worker in the existing `users` table using phone number or normalized name. It links the audio submission to that person when a match is found.

It does not create a new person just because an audio file was uploaded.

After submission, I can see the recording in **Audio Submissions** and play it directly from the dashboard.

---

# Audio information stored in SQL

For each audio submission, my database stores:

```text
Name
Phone
User ID when matched
Original filename
Stored filename
File path
Duration
Sample rate
Bitrate
Loudness
Quality estimate
File size
Submission time
```

The important audio measurements required by the assignment are:

```text
Duration
Sample rate (kHz)
Bitrate
Loudness (dB/LUFS)
```

The quality estimate is a simple rough estimate, not a professional audio-quality score.

---

# How I test the audio feature

1. Run the project:

```bash
python3 merge_users.py
```

2. Wait for the browser dashboard to open.

3. Go to **Audio Collection**.

4. Enter a worker name and phone number.

5. Choose a small WAV, MP3 or another supported audio file.

6. Click **Submit Audio**.

7. Scroll to **Audio Submissions**.

8. Check the extracted properties.

9. Click the audio player to listen to the recording.

For the best metadata results, I install FFmpeg before testing MP3/M4A and other compressed formats.

---

# n8n automation setup

The project creates:

```text
n8n_talentgraph_duplicate_alert.json
```

I can use this file in n8n.

The basic steps are:

1. Start n8n.
2. Create or open a workflow.
3. Import `n8n_talentgraph_duplicate_alert.json`.
4. Configure the SQLite node to point to my `db/users.db` database.
5. Activate or test the webhook.
6. Send a test person to the webhook.
7. Use a person that already exists in my database to test the duplicate path.
8. Show the duplicate result in n8n.

Example test data:

```json
{
  "name": "Arjun Mehta",
  "email": "arjun@example.com",
  "phone": "9000000131",
  "city": "Delhi"
}
```

The workflow checks the database and returns a duplicate result when a matching record is found.

The exact n8n SQLite credential/node settings can depend on whether I use n8n Cloud or a self-hosted n8n installation, so I need to configure the database connection in my n8n environment before running the workflow.

---

# What happens if the data has a problem?

Real-world data is not always clean, so my program also looks for data-quality problems.

Examples include:

- Missing information
- Incorrect phone formats
- Incorrect date formats
- Duplicate records
- Conflicting information
- Corrupted rows
- Different ways of writing the same information

The program records these problems in the:

```text
data_quality_issues
```

table inside my SQLite database.

I also keep a written explanation in:

```text
DATA_QUALITY_REPORT.md
```

---

# How I can view the SQL database directly

If I want to look at the database itself, I can use a SQLite extension in VS Code.

I can install a **SQLite Viewer** extension, then open:

```text
db/users.db
```

I can also check the database from Terminal.

For example:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('db/users.db')
for row in conn.execute('SELECT full_name, primary_email, matched_sources FROM users LIMIT 10'):
    print(row)
"
```

This prints the first 10 people from the `users` table.

I can also check audio submissions:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('db/users.db')
for row in conn.execute('SELECT name, phone, duration_seconds, sample_rate_hz, bitrate_kbps, loudness_db, quality_estimate FROM audio_submissions ORDER BY id DESC'):
    print(row)
"
```

---

# A simple example of the complete process

Imagine the three files contain information about the same person.

One file might have:

```text
Name: Arjun Mehta
Phone: 9000000131
```

Another file might have:

```text
Name: ARJUN MEHTA
Phone: +91-9000000131
```

My program cleans and compares the values instead of treating them as completely different people.

If the records can be safely matched, the information is connected to the same person in the SQL database.

If the program cannot safely prove that two records belong to the same person, it keeps them separate instead of making a risky merge.

Then the same worker can submit an audio recording from the dashboard. The audio submission is stored separately and can be linked to the existing person record when the phone or normalized name matches.

---

# If something does not work

If I get:

```text
zsh: command not found: python
```

I use:

```bash
python3 --version
```

and run the project with:

```bash
python3 merge_users.py
```

If I get an error about a missing package, I first make sure my virtual environment is active:

```bash
source venv/bin/activate
```

Then I run:

```bash
python3 -m pip install -r requirements.txt
```

If the program says that it cannot find a CSV file, I check that these files exist in my `data` folder:

```text
source1_naukri_applicants.csv
source2_gig_workers.csv
source3_cbnexus_contacts.csv
```

If the audio metadata says `unknown` for an MP3/M4A file, I check whether FFmpeg is installed:

```bash
ffprobe -version
```

If it is not installed on macOS, I can install it with:

```bash
brew install ffmpeg
```

If the dashboard works but an audio upload fails, I first check that the file is one of the supported formats and is smaller than 25 MB.

---

# GitHub setup

After testing the project, I can put it on GitHub.

First I initialize Git:

```bash
git init
```

Then I add my files:

```bash
git add .
```

Then I create the first commit:

```bash
git commit -m "Build TalentGraph data merge and audio collection app"
```

Then I connect my GitHub repository:

```bash
git remote add origin YOUR_GITHUB_REPOSITORY_URL
```

Then I push it:

```bash
git branch -M main
git push -u origin main
```

I should not upload private data, API keys, passwords, or sensitive production audio recordings to GitHub.

For a real submission, I would also add a `.gitignore` for the virtual environment, local database, uploaded audio, and other generated files if the assignment does not require the actual data files in the repository.

---

# How I would demonstrate the project in my video

I would show the tasks in this order:

### 1. Show the three CSV files

```text
source1_naukri_applicants.csv
source2_gig_workers.csv
source3_cbnexus_contacts.csv
```

### 2. Run the Python pipeline

```bash
python3 merge_users.py
```

### 3. Show the SQL database

Open:

```text
db/users.db
```

and show the `users` table and source tables.

### 4. Search for a person

Search by name and then search by a city that has multiple people. Show that the city search returns all matching people.

### 5. Show the data-quality report

Open:

```text
DATA_QUALITY_REPORT.md
```

### 6. Show the audio app

Enter a name and phone number, upload a recording, submit it, then show the metadata and play the recording.

### 7. Show n8n

Import:

```text
n8n_talentgraph_duplicate_alert.json
```

Configure the database, execute the workflow, and show a duplicate result.

### 8. Explain the 5,000-worker plan

Open:

```text
STRETCH.md
```

and briefly explain the production changes I would make.

---

# In short

My TalentGraph project takes messy information from three different sources and turns it into one cleaner SQL database.

The complete flow is:

```text
CSV files
   ↓
Python data cleaning
   ↓
Identity matching
   ↓
SQLite database
   ↓
Searchable dashboard
   ↓
Audio collection
   ↓
Audio metadata in SQL
   ↓
n8n duplicate automation
```

The main file I need to run is:

```text
merge_users.py
```

The main database is:

```text
db/users.db
```

The n8n workflow is:

```text
n8n_talentgraph_duplicate_alert.json
```

The data-quality explanation is:

```text
DATA_QUALITY_REPORT.md
```

The scaling plan is:

```text
STRETCH.md
```

The main thing I can do after running the project is search for people, see their combined information, collect worker audio, see the extracted audio properties, and demonstrate a real no-code duplicate-check workflow.

---

# requirements.txt

# TalentGraph
# Python 3.11+ recommended
# The core application uses Python standard-library modules for SQLite,
# CSV processing, the local HTTP dashboard, and WAV metadata extraction.
# No third-party package is required for the core merge/dashboard/audio flow.

# Optional: install these only if you later extend the project with
# additional audio/data-processing features.
# pandas>=2.0,<3.0
