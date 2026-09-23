# -*- coding: utf-8 -*-
"""
services/interpretation_docx.py — Export de l'interprétation IA en .docx.

Logique pure : reçoit le texte Markdown déjà généré (services/llm_client.py)
et le convertit en document Word mis en forme (titres, listes, gras/italique).
Aucun appel Streamlit ici ; components/tab_interpretation.py appelle
build_docx_bytes() et propose le résultat via st.download_button.

Le Markdown accepté est volontairement limité à ce que produit le prompt de
llm_client.py : titres «## », listes à puces « - »/« * », emphase **gras**
et *italique* sur une seule ligne (pas d'imbrication, pas de tableaux).

Modèle d'entreprise (optionnel) :
Si `template_path` est fourni, le document Word de l'entreprise (en-tête,
pied de page, logo, styles maison) est utilisé comme base, et le contenu est
inséré :
  - à l'emplacement d'un repère texte (paragraphe contenant exactement
    PLACEHOLDER, par défaut "{{INTERPRETATION}}"), sur sa propre ligne, si le
    modèle en contient un — méthode la plus fiable ;
  - sinon, à la fin du modèle, précédé d'un saut de page.
Les styles de titre et de liste du modèle sont réutilisés quand ils existent
sous un nom courant (français ou anglais) ; sinon, on retombe sur du gras
simple pour ne jamais faire échouer l'export à cause d'un nom de style
inconnu.
"""

import io
import re
from datetime import datetime

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph

_INLINE_RE = re.compile(r"(\*\*.+?\*\*|\*.+?\*)")
_ACCENT = RGBColor(0x2C, 0x7B, 0xE5)  # couleur d'accent des graphiques matplotlib

DEFAULT_PLACEHOLDER = "{{INTERPRETATION}}"

# Noms de style essayés dans l'ordre, pour s'adapter à un modèle en français
# ou en anglais sans connaître son gabarit à l'avance.
_HEADING_STYLE_CANDIDATES = {
    2: ["Heading 2", "Titre 2"],
    3: ["Heading 3", "Titre 3"],
}
_BULLET_STYLE_CANDIDATES = ["List Bullet", "Liste à puces", "List Paragraph"]


def _first_existing_style(document, candidates):
    """Retourne le premier nom de style de `candidates` présent dans le
    document, ou None si aucun n'existe (le modèle a pu les renommer)."""
    available = {s.name for s in document.styles}
    for name in candidates:
        if name in available:
            return name
    return None


def _add_inline_runs(paragraph, text):
    """Ajoute `text` à `paragraph` en gérant **gras** et *italique* simples
    (segments non imbriqués, sur une seule ligne)."""
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 3:
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 1:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def _set_base_style(document):
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)


def _add_heading(document, text, level, heading_styles):
    """Ajoute un titre en réutilisant le style du modèle s'il existe sous un
    nom connu ; sinon, un paragraphe en gras (jamais d'échec sur un style
    absent, ce qui arriverait avec add_heading() sur un modèle renommé)."""
    style_name = heading_styles.get(level)
    if style_name:
        document.add_paragraph(text, style=style_name)
    else:
        p = document.add_paragraph()
        p.add_run(text).bold = True


def markdown_to_document(document, markdown_text, *, heading_styles=None, bullet_style=None):
    """Ajoute le contenu Markdown au document Word déjà ouvert, paragraphe
    par paragraphe. Les lignes vides séparent les paragraphes sans en créer
    de vides (Word gère l'espacement via le style).

    `heading_styles` / `bullet_style` : noms de style à réutiliser (issus du
    modèle d'entreprise le cas échéant) ; None pour les styles par défaut de
    python-docx."""
    heading_styles = heading_styles or {2: "Heading 2", 3: "Heading 3"}

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("## "):
            _add_heading(document, line[3:].strip(), 2, heading_styles)
        elif line.startswith("### "):
            _add_heading(document, line[4:].strip(), 3, heading_styles)
        elif line.startswith(("- ", "* ")):
            if bullet_style:
                p = document.add_paragraph(style=bullet_style)
            else:
                p = document.add_paragraph()
                p.add_run("• ")
            _add_inline_runs(p, line[2:].strip())
        else:
            p = document.add_paragraph()
            _add_inline_runs(p, line)


def _find_placeholder_paragraph(document, placeholder):
    """Cherche un paragraphe dont le texte complet (une fois les espaces
    superflus retirés) est exactement `placeholder`. Retourne None si
    absent — un repère à cheval sur plusieurs « runs » Word (fréquent après
    une frappe avec correcteur orthographique) ne serait pas détecté ; dans
    ce cas, écrire le repère d'un seul bloc dans le modèle."""
    for p in document.paragraphs:
        if p.text.strip() == placeholder:
            return p
    return None


def _insert_paragraph_after(paragraph, text="", style=None):
    """python-docx ne fournit pas d'équivalent à add_paragraph() qui insère
    à un endroit précis (seulement en fin de document) : on manipule
    directement le XML pour créer un nouveau paragraphe juste après
    `paragraph`, aux mêmes marges de section."""
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    new_paragraph = Paragraph(new_p, paragraph._parent)
    if text:
        new_paragraph.add_run(text)
    if style:
        new_paragraph.style = style
    return new_paragraph


def _fill_content(document, target_name, model, generated_at, markdown_text, disclaimer,
                   heading_styles, bullet_style, insert_after=None):
    """Écrit le titre, les métadonnées, le corps et l'avertissement. Si
    `insert_after` est fourni, chaque élément est inséré juste après le
    précédent à cet endroit du document (cas du repère) ; sinon, tout est
    ajouté à la fin (document vierge, ou modèle sans repère)."""

    def add_paragraph(style=None):
        nonlocal insert_after
        if insert_after is not None:
            p = _insert_paragraph_after(insert_after, style=style)
            insert_after = p
            return p
        return document.add_paragraph(style=style)

    if insert_after is None:
        _add_heading(document, "Interprétation piézométrique", 2, heading_styles)
    else:
        p = add_paragraph()
        p.add_run("Interprétation piézométrique").bold = True

    meta = add_paragraph()
    meta.add_run(f"Piézomètre cible : {target_name}").italic = True
    meta.add_run().add_break(WD_BREAK.LINE)
    meta.add_run(
        f"Généré le {generated_at.strftime('%d/%m/%Y à %H:%M')} — modèle {model}"
    ).italic = True

    add_paragraph()  # espacement avant le corps

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            style = heading_styles.get(2)
            p = add_paragraph(style=style)
            if not style:
                p.add_run(line[3:].strip()).bold = True
            else:
                p.add_run(line[3:].strip())
        elif line.startswith("### "):
            style = heading_styles.get(3)
            p = add_paragraph(style=style)
            if not style:
                p.add_run(line[4:].strip()).bold = True
            else:
                p.add_run(line[4:].strip())
        elif line.startswith(("- ", "* ")):
            p = add_paragraph(style=bullet_style)
            if not bullet_style:
                p.add_run("• ")
            _add_inline_runs(p, line[2:].strip())
        else:
            p = add_paragraph()
            _add_inline_runs(p, line)

    add_paragraph()
    note = add_paragraph()
    note.add_run(disclaimer).italic = True
    for run in note.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    note.alignment = WD_ALIGN_PARAGRAPH.LEFT


def build_docx_bytes(
    *,
    markdown_text,
    target_name,
    model,
    generated_at=None,
    disclaimer=(
        "Texte généré par IA à partir d'une synthèse chiffrée calculée par "
        "l'application. À relire et valider avant tout usage : il ne "
        "remplace pas l'avis d'un hydrogéologue."
    ),
    template_path=None,
    placeholder=DEFAULT_PLACEHOLDER,
):
    """Construit un .docx et retourne son contenu en bytes, prêt pour
    st.download_button.

    `generated_at` : datetime, par défaut l'instant présent.

    `template_path` : chemin (ou fichier-objet) vers le modèle Word de
    l'entreprise. S'il est fourni :
      - un paragraphe dont le texte est exactement `placeholder` est
        recherché, et le contenu y est inséré à sa place (le paragraphe
        repère lui-même est retiré) ;
      - à défaut, le contenu est ajouté à la fin du modèle, précédé d'un
        saut de page ;
      - les styles de titre et de liste du modèle sont réutilisés quand
        leur nom est reconnu (voir _HEADING_STYLE_CANDIDATES /
        _BULLET_STYLE_CANDIDATES), sinon on retombe sur du gras simple.
    Sans `template_path`, un document vierge est créé (comportement
    précédent, inchangé)."""
    generated_at = generated_at or datetime.now()

    if template_path is not None:
        try:
            document = Document(template_path)
        except PackageNotFoundError as exc:
            # python-docx lève sa propre exception, y compris quand le
            # fichier n'existe simplement pas : on la traduit en
            # FileNotFoundError, standard et attendu par l'appelant.
            raise FileNotFoundError(
                f"Modèle Word introuvable ou invalide : {template_path}"
            ) from exc
        heading_styles = {
            level: _first_existing_style(document, names)
            for level, names in _HEADING_STYLE_CANDIDATES.items()
        }
        bullet_style = _first_existing_style(document, _BULLET_STYLE_CANDIDATES)

        anchor = _find_placeholder_paragraph(document, placeholder)
        if anchor is not None:
            insert_after = anchor
            _fill_content(
                document, target_name, model, generated_at, markdown_text, disclaimer,
                heading_styles, bullet_style, insert_after=insert_after,
            )
            anchor._p.getparent().remove(anchor._p)
        else:
            document.add_page_break()
            _fill_content(
                document, target_name, model, generated_at, markdown_text, disclaimer,
                heading_styles, bullet_style, insert_after=None,
            )
    else:
        document = Document()
        _set_base_style(document)
        _fill_content(
            document, target_name, model, generated_at, markdown_text, disclaimer,
            {2: "Heading 2", 3: "Heading 3"}, "List Bullet", insert_after=None,
        )

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
