"""Original course notes with deliberate typography and vector teaching figures."""
from io import BytesIO
from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, CondPageBreak, KeepTogether, Table, TableStyle, Flowable

INK=colors.HexColor('#172a3e');MUTED=colors.HexColor('#66798b');LINE=colors.HexColor('#dce5ec')

def printable(text):
    """Keep formulae readable even on a minimal host with Vera's smaller glyph set."""
    font=pdfmetrics.getFont('RC');glyphs=font.face.charToGlyph
    fallback={'−':'-','→':' -> ','←':' <- ','⇌':' <=> ','Δ':'Delta ','λ':'lambda','θ':'theta','π':'pi','Ω':'ohm','ρ':'rho','₀':'0','₁':'1','₂':'2','₃':'3','₄':'4','₅':'5','₆':'6','₇':'7','₈':'8','₉':'9','ₙ':'n','ₛ':'s','ₚ':'p','ₖ':'k','⁰':'^0','¹':'^1','²':'^2','³':'^3','⁴':'^4','⁵':'^5','⁶':'^6','⁻':'-','ⁿ':'^n','ᵐ':'^m','½':'1/2','¼':'1/4','⁺':'+','≥':'>=','≤':'<=','≈':'~','√':'sqrt','×':' x ','÷':' / '}
    return ''.join(c if ord(c) in glyphs else fallback.get(c,c.encode('ascii','replace').decode()) for c in str(text))

def setup_fonts():
    if 'RC' in pdfmetrics.getRegisteredFontNames():return
    pairs=[('C:/Windows/Fonts/segoeui.ttf','C:/Windows/Fonts/segoeuib.ttf'),('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    for regular,bold in pairs:
        if Path(regular).exists():
            pdfmetrics.registerFont(TTFont('RC',regular));pdfmetrics.registerFont(TTFont('RC-Bold',bold));pdfmetrics.registerFontFamily('RC',normal='RC',bold='RC-Bold',italic='RC',boldItalic='RC-Bold');return
    # ReportLab's bundled Vera fonts also work on minimal Render images.
    import reportlab
    fonts=Path(reportlab.__file__).parent/'fonts'
    pdfmetrics.registerFont(TTFont('RC',str(fonts/'Vera.ttf')));pdfmetrics.registerFont(TTFont('RC-Bold',str(fonts/'VeraBd.ttf')))
    pdfmetrics.registerFontFamily('RC',normal='RC',bold='RC-Bold',italic='RC',boldItalic='RC-Bold')

class Figure(Flowable):
    def __init__(self,kind,accent):super().__init__();self.kind=kind;self.accent=accent;self.width=475;self.height=126
    def draw(self):
        c=self.canv;c.setFillColor(colors.HexColor('#f3f7fa'));c.roundRect(0,0,self.width,self.height,12,fill=1,stroke=0);c.setStrokeColor(self.accent);c.setLineWidth(1.8);c.setFont('RC',9);c.setFillColor(INK)
        if self.kind=='cell':
            c.roundRect(28,18,190,92,25,fill=0);c.ellipse(90,45,142,85,fill=0);c.drawString(104,61,'DNA');c.line(150,69,270,92);c.drawString(277,89,'Nucleus: genetic information');c.line(44,34,270,31);c.drawString(277,28,'Membrane: selective boundary');c.ellipse(55,65,77,79);c.line(65,78,270,61);c.drawString(277,58,'Mitochondrion: respiration')
        elif self.kind=='wave':
            import math
            path=c.beginPath()
            for i in range(360):
                x=35+i;y=61+28*math.sin(i/180*2*math.pi)
                path.moveTo(x,y) if i==0 else path.lineTo(x,y)
            c.drawPath(path);c.setDash(3,3);c.line(35,61,420,61);c.setDash();c.line(80,103,260,103);c.drawCentredString(170,111,'One wavelength');c.drawString(350,14,'Energy transfer ->')
        elif self.kind=='motion':
            c.line(50,25,430,25);c.line(50,25,50,108);c.line(50,45,350,97);c.drawString(13,110,'v');c.drawString(434,22,'t');c.drawString(220,98,'Gradient = acceleration');c.drawString(155,12,'Area below line = displacement')
        elif self.kind=='cpu':
            for x,label in [(30,'Memory'),(200,'Control unit'),(355,'ALU')]:
                c.roundRect(x,48,105,42,8);c.drawCentredString(x+52,65,label)
            c.line(135,70,200,70);c.line(305,70,355,70);c.drawString(165,20,'Registers hold working data and addresses')
        elif self.kind=='inheritance':
            for x in range(3):c.line(90+x*55,20,90+x*55,113)
            for y in range(3):c.line(90,20+y*46,200,20+y*46)
            for x,y,text in [(110,80,'TT'),(165,80,'Tt'),(110,34,'Tt'),(165,34,'tt')]:c.drawString(x,y,text)
            c.drawString(245,80,'Tt × Tt');c.drawString(245,57,'Three dominant phenotypes');c.drawString(245,34,'One recessive phenotype')
        elif self.kind=='circuit':
            c.rect(60,30,320,65,fill=0);c.setFillColor(colors.HexColor('#f3f7fa'));c.rect(185,84,70,24,fill=1,stroke=0);c.setFillColor(INK);c.rect(185,84,70,22,fill=0);c.drawCentredString(220,91,'R');c.line(58,58,58,82);c.line(67,63,67,77);c.drawString(95,10,'Current flows around the complete circuit')

def make_pdf(course,topics,book=False):
    setup_fonts();accent=colors.HexColor(course['colour']);out=BytesIO();width=A4[0]-120
    style={
      'kicker':ParagraphStyle('k',fontName='RC-Bold',fontSize=8.5,leading=12,textColor=accent,spaceAfter=8),
      'title':ParagraphStyle('t',fontName='RC-Bold',fontSize=26,leading=32,textColor=INK,spaceAfter=13),
      'subtitle':ParagraphStyle('st',fontName='RC',fontSize=10,leading=15,textColor=MUTED,spaceAfter=16),
      'heading':ParagraphStyle('h',fontName='RC-Bold',fontSize=12,leading=17,textColor=INK,spaceBefore=12,spaceAfter=6,keepWithNext=True),
      'body':ParagraphStyle('b',fontName='RC',fontSize=10,leading=15.5,textColor=INK,spaceAfter=7),
      'small':ParagraphStyle('s',fontName='RC',fontSize=8,leading=12,textColor=MUTED,spaceAfter=5),
      'table':ParagraphStyle('tb',fontName='RC',fontSize=8.5,leading=12.5,textColor=INK),
      'code':ParagraphStyle('code',fontName='RC',fontSize=8.5,leading=13,textColor=INK,leftIndent=10,backColor=colors.HexColor('#f3f7fa'),spaceBefore=8,spaceAfter=10),
    }
    def p(text,kind='body'):
        text=printable(text).replace('–','-').replace('—','-').replace('‑','-')
        text=escape(text).replace('\n','<br/>')
        if kind=='code':text=text.replace(' ','&nbsp;')
        return Paragraph(text,style[kind])
    def box(label,text,bg='#eef5fc'):
        table=Table([[p(label,'kicker')],[p(text)]],colWidths=[width])
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(bg)),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,0),10),('BOTTOMPADDING',(0,-1),(-1,-1),10)]))
        return table
    def footer(c,doc):
        w,h=A4;c.setFillColor(accent);c.rect(0,h-7,w,7,fill=1,stroke=0)
        c.setFont('RC-Bold',9);c.setFillColor(INK);c.drawString(48,h-34,'REVISIONCORE')
        c.setFont('RC',8);c.setFillColor(MUTED);c.drawRightString(w-48,h-34,course['board']+'  |  '+course['id'])
        c.setStrokeColor(LINE);c.line(48,43,w-48,43);c.setFont('RC',7.2);c.drawString(48,29,'Original expanded edition | 2027 | Independent teacher review pending');c.drawRightString(w-48,29,str(doc.page))
    story=[]
    if book:
        story += [Spacer(1,65),p(course['board'].upper()+' / '+course['qualification'].upper(),'kicker'),p(course['subject'],'title'),p('Expanded revision notebook | '+course['id'],'subtitle'),Spacer(1,15),box('UNDERSTAND. APPLY. RECALL.','Explanations, key vocabulary, worked reasoning and topic questions with explicit marking points.'),Spacer(1,20),p('In this book','heading')]
        for i,t in enumerate(topics,1):story.append(p(f'{i:02}   {t["title"]}','small'))
        story += [Spacer(1,14),p('These original chapters cover the areas listed here. This is not certified statement-by-statement specification coverage. Use the official specification and teacher guidance alongside the notes.','small'),PageBreak()]
    for number,t in enumerate(topics,1):
        if number>1:story.append(PageBreak())
        story += [p(t['chapter'].upper(),'kicker'),p(t['title'],'title'),p(course['qualification']+' | '+course['id']+' | '+t['track'],'subtitle')]
        if t.get('objectives'):story += [box('WHAT YOU WILL STUDY',' / '.join(t['objectives'])),Spacer(1,5)]
        for section in t['sections']:story += [p(section['heading'],'heading'),p(section['body'])]
        if t.get('formula'):story += [Spacer(1,10),box('KEEP THIS RELATIONSHIP',t['formula'])]
        if t.get('diagram'):story += [Spacer(1,12),Figure(t['diagram'],accent)]
        if t.get('comparison_table'):
            v=t['comparison_table'];rows=[[p(h,'table') for h in v['headers']]]+[[p(cell,'table') for cell in row] for row in v['rows']]
            table=Table(rows,colWidths=[width/len(v['headers'])]*len(v['headers']),repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf1f8')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f8fa')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,-1),.4,LINE)]))
            story += [p('Compare the evidence','heading'),table]
        if t.get('practical'):
            story.append(p('Practical thinking','heading'))
            for label,value in t['practical'].items():story.append(p(label.capitalize()+': '+('; '.join(value) if isinstance(value,list) else value)))
        if t.get('code_example'):story += [p('Trace the algorithm','heading'),p(t['code_example'],'code')]
        story.append(p('Key vocabulary','heading'))
        for term in t.get('key_terms',[]):story.append(p(term['term']+' - '+term['definition']))
        story += [Spacer(1,8),box('EXAM TECHNIQUE',t['tip'],'#fff7e8')]
        if t.get('misconception')!=t.get('tip'):story += [Spacer(1,10),box('COMMON MISCONCEPTION',t['misconception'],'#fff7e8')]
        story += [CondPageBreak(240),Spacer(1,22),p('APPLY / '+course['id'],'kicker'),p('See the reasoning.','title'),p(t['title'],'subtitle')]
        for i,example in enumerate(t.get('worked_examples',[t['worked']]),1):
            example_block=[p(f'Worked example {i}','heading'),p(example['question'])]
            for j,step in enumerate(example['steps'],1):example_block.append(p(f'{j:02}   '+step))
            story += [KeepTogether(example_block),Spacer(1,13)]
        story += [box('MAKE THE METHOD YOURS','Cover the solution and explain why each step follows. Then answer the question independently and check the method, units and conclusion.'),PageBreak(),p('RECALL / '+course['id'],'kicker'),p('Test your understanding.','title'),p('Try the questions before reading the answer guide on the following page. These are original practice tasks.','subtitle')]
        for i,q in enumerate(t['questions'],1):
            story += [p(f'{i:02}   '+q['prompt'],'heading'),p(str(q['marks'])+(' mark' if q['marks']==1 else ' marks'),'small'),Spacer(1,16)]
        story += [PageBreak(),p('CHECK / '+course['id'],'kicker'),p('Answer guide.','title'),p('Award only the points supported by your answer. Equivalent accurate wording is acceptable; use teacher guidance for borderline cases.','subtitle')]
        for i,q in enumerate(t['questions'],1):
            story.append(p(f'{i:02}   '+q['prompt'],'heading'))
            for mark in q['mark_scheme']:story.append(p(str(mark['marks'])+' mark: '+mark['text']))
        story += [Spacer(1,12),p('Course reference','heading'),Paragraph('<link href="'+escape(t['source'],quote=True)+'" color="#357cff">Official specification: '+escape(course['board']+' '+course['id'])+'</link>',style['small']),p('Original revision material. Independent subject-teacher review and a complete specification audit are pending.','small')]
    doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=60,leftMargin=60,topMargin=65,bottomMargin=62,title=course['subject']+' | RevisionCore',author='RevisionCore',pageCompression=1)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
