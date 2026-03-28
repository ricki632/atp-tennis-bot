import requests
import json
import os
from datetime import datetime

# ─── CONFIGURAZIONE (non toccare, vengono da GitHub Secrets) ───
RAPIDAPI_KEY       = os.environ["RAPIDAPI_KEY"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN     = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

TODAY = datetime.utcnow().strftime("%Y-%m-%d")

# ─── 1. RECUPERA PARTITE ATP DEL GIORNO ───────────────────────
def get_atp_matches():
    url = f"https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2/atp/fixtures/{TODAY}"
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": "tennis-api-atp-wta-itf.p.rapidapi.com",
        "x-rapidapi-key": RAPIDAPI_KEY
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        # DEBUG: stampa la struttura grezza per capire il formato
        print(f"[DEBUG] Chiavi risposta API: {list(data.keys())}")
        print(f"[DEBUG] Primi 500 caratteri: {str(data)[:500]}")

        matches = data.get("data", data.get("result", data.get("fixtures", [])))
        if isinstance(matches, dict):
            matches = matches.get("fixtures", data.get("data", []))
        if not isinstance(matches, list):
            matches = []
        print(f"[OK] Trovate {len(matches)} partite ATP per {TODAY}")
        return matches
    except Exception as e:
        print(f"[ERRORE] API Tennis: {e}")
        return []


# ─── 2. FORMATTA LE PARTITE PER CLAUDE ────────────────────────
def format_matches_for_claude(matches):
    if not matches:
        return None

    lines = []
    for i, m in enumerate(matches, 1):
        # Struttura API: player1/player2 + tournament
        p1_obj = m.get("player1", {}) or {}
        p2_obj = m.get("player2", {}) or {}
        tourn  = m.get("tournament", {}) or {}
        round_obj = m.get("round", {}) or {}

        p1 = p1_obj.get("name") or m.get("event_first_player", "Giocatore 1")
        p2 = p2_obj.get("name") or m.get("event_second_player", "Giocatore 2")
        tournament = tourn.get("name") or m.get("league_name", "Torneo sconosciuto")
        surface = tourn.get("surface") or m.get("event_surface", "N/D")
        round_name = round_obj.get("name", "") if isinstance(round_obj, dict) else str(round_obj)
        r1 = p1_obj.get("rank") or m.get("event_first_player_rank", "N/A")
        r2 = p2_obj.get("rank") or m.get("event_second_player_rank", "N/A")
        time = m.get("date", m.get("event_time", ""))[:10] if m.get("date") else ""

        lines.append(
            f"{i}. {p1} (ATP #{r1}) vs {p2} (ATP #{r2})\n"
            f"   Torneo: {tournament} | Superficie: {surface} | "
            f"Round: {round_name} | Orario: {time}"
        )

    return "\n".join(lines)


# ─── 3. ANALISI CON CLAUDE ────────────────────────────────────

SYSTEM_PROMPT = """Sei un analista quantitativo specializzato in tennis ATP maschile e value betting professionale.
Hai accesso a web_search: USALO per cercare informazioni fresche prima di analizzare ogni partita.

RICERCHE OBBLIGATORIE per ogni giocatore (in inglese per risultati migliori):
1. "[Player name] injury news today" — infortuni, fastidi, dichiarazioni pre-match
2. "[Player name] [tournament] 2026 press conference" — dichiarazioni ufficiali recenti
3. "[Player1] vs [Player2] odds [tournament] 2026" — quote attuali di mercato
4. "[Player name] recent results 2026" — forma recente se non la conosci

Se trovi notizie di infortuni o fastidi fisici dichiarati nelle ultime 48h → applica RED_FLAG V5 automaticamente.
Se trovi quote attuali → usale per calcolare P_implicita e Edge reali.
Se non trovi notizie rilevanti → procedi con la conoscenza interna.

Operi con metodo rigoroso, dati oggettivi e trasparenza totale sui limiti informativi.
Non esprimi opinioni soggettive. Ogni affermazione deve essere riconducibile a una variabile misurabile.

Applichi il seguente framework a 8 variabili (pesi totali = 100%):

V1 SUPERFICIE & ADATTAMENTO (25%): Win Rate sulla superficie specifica ultimi 18 mesi, Delta vs Win Rate globale, recency ultime 5 partite su quel manto. Scala 1-10.
V2 FORMA RECENTE (20%): Formula FR = (P1×2 + P2×1.5 + P3×1.2 + P4×1 + P5×0.8) / 6.5 dove Px = Titolo=10, Finale=8, SF=6, QF=4, R16=3, R32=2, R64=1, R128=0.5. +1 se ha battuto top-15 negli ultimi 2 match, -1 se 2 sconfitte consecutive da favorito.
V3 H2H (15%): Record totale + record sulla superficie specifica + ultimi 3 incontri (peso maggiore). Se H2H < 3 partite, peso ridotto al 50% ridistribuito su V1/V2. Scala 1-10.
V4 RANKING ELO vs ATP (15%): Gap ELO tra i due giocatori (fonte: TennisAbstract). Gap_Value = Posizione_ELO - Posizione_ATP. >+20 = sottovalutato dal mercato, <-20 = sopravvalutato. Scala 1-10.
V5 STATO FISICO & INFORTUNI (10%): Comunicazioni ufficiali, retirement ultimi 14 giorni (RED FLAG -3 punti al finale), numero tie-break e 3 set recenti. PRIORITÀ AI DATI TROVATI CON WEB SEARCH. Scala 1-10.
V6 CONTESTO TORNEO & MOTIVAZIONE (8%): Slam/M1000 con difesa titolo = 9-10; M1000 standard = 7-8; ATP500 = 5-6; ATP250 per top-10 = 3-4; fine stagione/obiettivi già raggiunti = 1-2.
V7 TATTICA & STILE (5%): Compatibilità stile di gioco sul matchup specifico. +2 se vantaggio tattico chiaro, -2 se svantaggio strutturale. Scala 1-10.
V8 QUOTE MERCATO (2%): Movimento quote apertura vs attuale su 3+ bookmaker. PRIORITÀ AI DATI TROVATI CON WEB SEARCH. In discesa = 7-9, stabile = 5, in salita = 2-4.

FORMULA VALUE SCORE: VS = (V1×0.25)+(V2×0.20)+(V3×0.15)+(V4×0.15)+(V5×0.10)+(V6×0.08)+(V7×0.05)+(V8×0.02)
PROBABILITÀ STIMATA: P_stim = VS_A / (VS_A + VS_B)
EDGE: Edge = P_stimata - P_implicita_corretta (dove P_implicita_corretta = normalizzata sul margine bookmaker)
QUOTA MINIMA: Quota_Fair = 1/P_stimata. Quota_Min = Quota_Fair × (1 + margine: 5% se ALTA, 8% se MEDIA, 12% se BASSA)

SOGLIE CONFIDENZA: VS 7.5-10 = ALTA | VS 6.0-7.4 = MEDIA | VS 4.5-5.9 = BASSA | <4.5 = SCARTA

RED FLAG AUTOMATICI:
- Retirement/walkover ultimi 14 giorni → penalità -3 al VS finale
- Infortunio dichiarato nelle ultime 48h → segnala in red_flags e abbassa V5 a 2-3
- Meno di 15 partite stagionali disputate
- H2H < 2 incontri + ELO simile (±30 punti)
- Quote ancora in forte movimento (<6h alla partita)

TIPOLOGIE BET:
- Favorito netto (quota <1.45): cerca Handicap Set -1.5 o Total Games Under
- Partita equilibrata (1.70-2.20): cerca Moneyline se Edge >7%, o Over/Under games per stile
- Outsider (quota >2.40): solo se VS outsider ≥6.5 + vantaggio su almeno una variabile chiave

Rispondi SEMPRE e SOLO con JSON valido. Nessun testo prima o dopo."""

ANALYSIS_PROMPT = """Analizza le seguenti partite ATP di oggi ({date}) applicando il framework completo.

Per ogni partita valuta ENTRAMBI i giocatori su tutte le 8 variabili usando le tue conoscenze aggiornate.
Identifica il giocatore con il VALUE SCORE più alto e costruisci la bet su di lui.
Includi SOLO le partite con Edge > 0 e Confidenza ALTA o MEDIA nel campo "classifica".
Segnala esplicitamente le partite con dati insufficienti.

PARTITE DI OGGI:
{matches}

Rispondi ESCLUSIVAMENTE con questo JSON (nessun testo prima o dopo):
{{
  "data": "{date}",
  "analisi": [
    {{
      "id": 1,
      "partita": "Giocatore A vs Giocatore B",
      "torneo": "Nome Torneo",
      "categoria": "Slam/M1000/ATP500/ATP250",
      "superficie": "Clay/Hard/Grass/Indoor Hard",
      "round": "R32/R16/QF/SF/F",
      "giocatore_analizzato": "Nome del giocatore su cui si punta",
      "ranking_atp": "ATP #XX",
      "elo_stimato": "XXXX (se disponibile)",
      "scoring": {{
        "V1_superficie": 7.5,
        "V2_forma": 8.0,
        "V3_h2h": 6.5,
        "V4_elo_atp": 7.0,
        "V5_fisico": 9.0,
        "V6_motivazione": 7.0,
        "V7_tattica": 6.0,
        "V8_quote": 5.0
      }},
      "value_score": 7.6,
      "probabilita_stimata": 62.5,
      "probabilita_implicita": 54.0,
      "edge": 8.5,
      "confidenza": "ALTA",
      "bet_tipo": "Moneyline/Handicap Set/Total Games Over/Total Games Under/Set Betting",
      "bet_selezione": "Descrizione esatta della selezione (es: Sinner vince in max 2 set)",
      "quota_fair": 1.60,
      "quota_minima": 1.68,
      "motivazione": "Spiegazione in 2-3 righe basata sulle variabili principali",
      "rischi": "Principale rischio da considerare",
      "red_flags": "Nessuno / Lista flag attivi",
      "dati_insufficienti": false,
      "limite_specifico": ""
    }}
  ],
  "classifica": [
    {{
      "posizione": 1,
      "partita": "X vs Y",
      "selezione": "Tipo bet - selezione",
      "value_score": 7.6,
      "edge": 8.5,
      "quota_minima": 1.68,
      "confidenza": "ALTA"
    }}
  ],
  "riepilogo": {{
    "totale_partite": 10,
    "partite_value": 3,
    "partite_insufficienti": 1,
    "partite_scartate": 6
  }}
}}"""


def analyze_with_claude(matches_text):
    prompt = ANALYSIS_PROMPT.format(date=TODAY, matches=matches_text)

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 8000,
                "system": SYSTEM_PROMPT,
                "tools": [
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 20
                    }
                ],
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=120
        )
        r.raise_for_status()
        response = r.json()

        # Estrai il testo finale — con web search Claude può restituire
        # più blocchi (tool_use + tool_result + text finale)
        raw = ""
        for block in response.get("content", []):
            if block.get("type") == "text":
                raw = block.get("text", "").strip()

        if not raw:
            print("[ERRORE] Nessun testo nella risposta Claude")
            return None

        # Pulizia sicura del JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        print(f"[OK] Claude ha analizzato {len(data.get('analisi', []))} partite")
        return data

    except Exception as e:
        print(f"[ERRORE] Claude API: {e}")
        return None


# ─── 4. FORMATTA MESSAGGIO TELEGRAM ───────────────────────────
def format_telegram_message(data):
    analisi = data.get("analisi", [])
    classifica = data.get("classifica", [])
    riepilogo = data.get("riepilogo", {})

    if not analisi:
        msg = "⚠️ Nessuna partita ATP trovata per oggi."
        return msg, ""

    date_fmt = datetime.utcnow().strftime("%d/%m/%Y")

    # ── MESSAGGIO 1: CLASSIFICA RAPIDA ──────────────────────────
    msg1 = f"🎾 <b>ATP VALUE BETS — {date_fmt}</b>\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if riepilogo:
        msg1 += (
            f"📊 Analizzate: <b>{riepilogo.get('totale_partite','?')}</b> partite  |  "
            f"✅ Value: <b>{riepilogo.get('partite_value','?')}</b>  |  "
            f"❌ Scartate: <b>{riepilogo.get('partite_scartate','?')}</b>\n\n"
        )

    if classifica:
        msg1 += "🏆 <b>CLASSIFICA VALUE BET (ordine Edge)</b>\n\n"
        medals = ["🥇","🥈","🥉"]
        for i, item in enumerate(classifica):
            icon = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            conf = item.get("confidenza","")
            conf_icon = "🟢" if conf == "ALTA" else "🟡"
            msg1 += (
                f"{icon} <b>{item.get('partita','?')}</b>\n"
                f"   💡 {item.get('selezione','?')}\n"
                f"   📈 Edge: <b>+{item.get('edge','?')}%</b>  |  "
                f"VS: <b>{item.get('value_score','?')}/10</b>  |  "
                f"Quota ≥ <b>{item.get('quota_minima','?')}</b>  "
                f"{conf_icon}\n\n"
            )
    else:
        msg1 += "⚠️ Nessuna bet con edge positivo oggi.\n"

    msg1 += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg1 += "<i>Dettaglio analisi nel messaggio successivo ↓</i>"

    # ── MESSAGGIO 2: DETTAGLIO PARTITE (solo quelle con edge positivo) ──
    value_matches = [m for m in analisi
                     if m.get("edge", 0) > 0
                     and m.get("confidenza") in ("ALTA", "MEDIA")
                     and not m.get("dati_insufficienti", False)]

    details = []
    for m in value_matches:
        scoring = m.get("scoring", {})
        conf = m.get("confidenza","")
        conf_icon = "🟢" if conf == "ALTA" else "🟡"
        red = m.get("red_flags","Nessuno")
        red_line = f"\n⚠️ <i>Red flag: {red}</i>" if red and red != "Nessuno" else ""

        block = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>{m.get('partita','?')}</b>\n"
            f"🏆 {m.get('torneo','?')} [{m.get('categoria','?')}]  |  "
            f"🎾 {m.get('superficie','?')}  |  📍 {m.get('round','?')}\n\n"
            f"👤 <b>Puntato su:</b> {m.get('giocatore_analizzato','?')} "
            f"({m.get('ranking_atp','?')})\n\n"
            f"<b>SCORING DETTAGLIATO:</b>\n"
            f"  V1 Superficie:   {scoring.get('V1_superficie','?')}/10\n"
            f"  V2 Forma:        {scoring.get('V2_forma','?')}/10\n"
            f"  V3 H2H:          {scoring.get('V3_h2h','?')}/10\n"
            f"  V4 ELO/ATP:      {scoring.get('V4_elo_atp','?')}/10\n"
            f"  V5 Fisico:       {scoring.get('V5_fisico','?')}/10\n"
            f"  V6 Motivazione:  {scoring.get('V6_motivazione','?')}/10\n"
            f"  V7 Tattica:      {scoring.get('V7_tattica','?')}/10\n"
            f"  V8 Quote:        {scoring.get('V8_quote','?')}/10\n\n"
            f"📊 <b>Value Score: {m.get('value_score','?')}/10</b>\n"
            f"📈 P. stimata: <b>{m.get('probabilita_stimata','?')}%</b>  |  "
            f"P. implicita: {m.get('probabilita_implicita','?')}%  |  "
            f"Edge: <b>+{m.get('edge','?')}%</b>\n"
            f"{conf_icon} Confidenza: <b>{conf}</b>\n\n"
            f"💡 <b>BET:</b> {m.get('bet_tipo','?')}\n"
            f"   ▶ {m.get('bet_selezione','?')}\n"
            f"   Quota Fair: {m.get('quota_fair','?')}  |  "
            f"Quota Min: <b>{m.get('quota_minima','?')}</b>\n\n"
            f"📝 {m.get('motivazione','')}\n"
            f"⚠️ <i>Rischio: {m.get('rischi','N/A')}</i>"
            f"{red_line}"
        )
        details.append(block)

    # Partite con dati insufficienti
    insufficient = [m for m in analisi if m.get("dati_insufficienti", False)]
    if insufficient:
        block = "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>DATI INSUFFICIENTI</b>\n"
        for m in insufficient:
            block += f"  • {m.get('partita','?')} → {m.get('limite_specifico','Dati incompleti')}\n"
        details.append(block)

    msg2 = "\n\n".join(details) if details else "ℹ️ Nessuna partita con analisi dettagliata disponibile."
    msg2 += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Solo scopo informativo. Gioca responsabilmente. 18+</i>"

    return msg1, msg2


# ─── 5. INVIA SU TELEGRAM ─────────────────────────────────────
def send_telegram(message):
    # Telegram limita i messaggi a 4096 caratteri
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]

    for chunk in chunks:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML"
                },
                timeout=15
            )
            r.raise_for_status()
            print("[OK] Messaggio inviato su Telegram")
        except Exception as e:
            print(f"[ERRORE] Telegram: {e}")


# ─── MAIN ─────────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  ATP TENNIS ANALYZER — {TODAY}")
    print(f"{'='*50}\n")

    # Step 1: Recupera partite
    matches = get_atp_matches()

    if not matches:
        msg = f"⚠️ <b>ATP Analyzer — {TODAY}</b>\n\nNessuna partita ATP trovata per oggi. Giorno di riposo o API non disponibile."
        send_telegram(msg)
        return

    # Step 2: Formatta per Claude
    matches_text = format_matches_for_claude(matches)
    if not matches_text:
        return

    # Step 3: Analisi Claude
    analysis = analyze_with_claude(matches_text)
    if not analysis:
        send_telegram("❌ Errore nell'analisi Claude. Controlla i log su GitHub Actions.")
        return

    # Step 4: Formatta e invia (2 messaggi: classifica + dettaglio)
    msg1, msg2 = format_telegram_message(analysis)
    send_telegram(msg1)
    if msg2:
        send_telegram(msg2)

    print("\n[COMPLETATO] Analisi inviata con successo!")


if __name__ == "__main__":
    main()
