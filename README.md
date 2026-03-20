# WealthOps Assistant

A desktop application that answers questions about WealthOps call recordings using AI. It knows what Christopher Nelson said about S-Corps in January. It knows what Milton De La Cruz thinks about DSCR loans. It knows things about your financial future that you haven't gotten around to watching yet, and it will never judge you for that.

Built because someone's mother-in-law wanted to ask questions about the calls, and apparently "just watch the recordings" was not a satisfactory answer. Fourteen hours of video content was converted into a searchable database, wired to a language model, wrapped in a desktop GUI, given an IRC client for technical support, and distributed via GitHub Actions — which, in hindsight, may have been a disproportionate response to the problem. But here we are.

## What It Does

You type a question. The app searches a local database of call recording summaries, finds the relevant discussions, hands them to Claude, and Claude explains what was said in plain English with references to the specific calls. Think of it as a research assistant who has watched every recording, taken meticulous notes, and has infinite patience for follow-up questions.

It does not have opinions on whether you should form an S-Corp. It will, however, tell you exactly what the people on the calls had to say about it, which is arguably more useful.

## Using the App

### First Launch

1. Double-click `WealthOps Assistant.exe`
2. Enter your Claude API key when prompted. If you don't know what this is, ask Travis. If you don't know who Travis is, you have downloaded the wrong software.
3. The app will download the call recording database. This takes a few seconds. A small animated dollar sign will keep you company during this time. It was chosen for thematic reasons.
4. You're in. Ask a question.

### Asking Questions

Type a question in the box at the bottom and press Enter. For example:

- "What tax strategies have been discussed?"
- "How should I set up bookkeeping?"
- "What did Christopher say about options trading?"
- "What is a DAF and why should I care?"

The app will search the recordings, think for a moment, and give you an answer with references to which calls the information came from. If it can't find anything relevant, it will tell you honestly rather than making something up. This is a feature, not a limitation.

You can ask follow-up questions. The app remembers what you've been talking about within a session. "Tell me more about that" works. "What about for someone my age?" works. It's a conversation, not a search engine.

### Clear Chat

Click `Clear Chat` when you want to change topics. This starts a fresh conversation. Your previous chat is saved and can be viewed later from History. Clearing is optional — you can keep asking related questions in the same session for as long as you want.

### History

Click `History` to see your past conversations. They're organized by date. Click any past session to read through it again. This costs nothing — past conversations are stored locally and don't require any API calls to review.

The History view is read-only. You cannot argue with your past self's questions, no matter how much you might want to.

### Help

Click `Help` to send a message to Travis via the in-app chat. He may not respond immediately. He may be at work, asleep, or debugging the very software you are currently using. If the chat doesn't connect, the app will offer to open an email instead.

### Settings

Click the gear icon to update your API key or check for database updates. You will need this approximately never, but it's there.

## How Updates Work

When new call recordings are added to the WealthOps community, the database gets updated. The next time you open the app, it silently checks for updates and downloads the new version if one is available. You don't need to do anything. You don't even need to know this is happening. The app is quietly self-improving in the background, which is either convenient or unsettling depending on your perspective.

## Cost

The app uses the Claude API, which costs money per question. Not much money — a typical question costs about one cent, and follow-up questions in the same session cost even less. Active daily use runs roughly $2–5 per month, which is less than a single fancy coffee and arguably more useful, assuming you were not in desperate need of that coffee.

## Things the App Cannot Do

- It cannot give you financial advice. It can only tell you what was discussed in the calls.
- It cannot access recordings that haven't been added to the database yet.
- It cannot make you watch the recordings. Nobody can make you watch the recordings. But now, at least, you don't have to.

## Technical Details for People Who Care About This Sort of Thing

The app is a Python/tkinter desktop application packaged with PyInstaller. It uses SQLite with FTS5 full-text search for retrieval, the Claude API with prompt caching for generation, and an embedded IRC client for the Help feature. The knowledge database is distributed via GitHub Releases with SHA256 integrity verification.

If none of that meant anything to you, that's fine. The app works the same either way.
