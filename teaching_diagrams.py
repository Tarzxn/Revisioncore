"""Draw the same labelled vector scenes used by the notes reader, without SVG dependencies."""
import json,math
from functools import lru_cache
from pathlib import Path
from reportlab.lib import colors
from reportlab.platypus import Flowable

@lru_cache(maxsize=1)
def scenes():
    return json.loads((Path(__file__).parent/'static'/'diagrams.json').read_text(encoding='utf-8'))

class TeachingDiagram(Flowable):
    def __init__(self,key,width=475):
        super().__init__();self.scene=scenes()[key];self.width=width;self.height=width*self.scene['height']/self.scene['width']
    def draw(self):
        # Coordinates are top-left in the source scenes and in the browser SVGs.
        c=self.canv;d=self.scene;scale=self.width/d['width'];c.saveState();c.scale(scale,scale)
        c.setFillColor(colors.HexColor('#f8fafc'));c.roundRect(0,0,d['width'],d['height'],10,fill=1,stroke=0)
        Y=lambda y:d['height']-y
        def line(x1,y1,x2,y2):c.line(x1,Y(y1),x2,Y(y2))
        for e in d['elements']:
            kind=e['kind'];colour=e.get('color','#172a3e');colour='#172a3e' if colour=='none' else colour;c.setStrokeColor(colors.HexColor(colour));c.setFillColor(colors.HexColor(colour));c.setLineWidth(e.get('width',2));c.setDash([5,5] if e.get('dash') else [])
            if kind=='text':
                # Font setup and Unicode fallback stay consistent with the rest of the PDF.
                from pdf_notes import printable
                c.setFont('RC',e.get('size',18));fn={'middle':c.drawCentredString,'end':c.drawRightString}.get(e.get('anchor'),c.drawString)
                fn(e['x'],Y(e['y']),printable(e['text']))
            elif kind in ('line','arrow'):
                line(e['x1'],e['y1'],e['x2'],e['y2'])
                if kind=='arrow':
                    a=math.atan2(e['y2']-e['y1'],e['x2']-e['x1'])
                    for off in (-.45,.45):line(e['x2'],e['y2'],e['x2']-10*math.cos(a+off),e['y2']-10*math.sin(a+off))
            else:
                fill=e.get('fill','none');stroke=e.get('color','none')!='none'
                if fill!='none':c.setFillColor(colors.HexColor(fill))
                if kind=='rect':c.roundRect(e['x'],Y(e['y']+e['h']),e['w'],e['h'],e.get('r',0),stroke=int(stroke),fill=int(fill!='none'))
                elif kind=='ellipse':c.ellipse(e['cx']-e['rx'],Y(e['cy']+e['ry']),e['cx']+e['rx'],Y(e['cy']-e['ry']),stroke=int(stroke),fill=int(fill!='none'))
                elif kind in ('polyline','polygon'):
                    path=c.beginPath();path.moveTo(e['points'][0][0],Y(e['points'][0][1]))
                    for x,y in e['points'][1:]:path.lineTo(x,Y(y))
                    if kind=='polygon':path.close()
                    c.drawPath(path,stroke=int(stroke),fill=int(fill!='none'))
        c.restoreState()
