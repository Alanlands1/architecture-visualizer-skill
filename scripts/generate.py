#!/usr/bin/env python3
"""Generate editable PPTX, Draw.io XML, DOCX and SVG from one architecture JSON model."""
import argparse, json, math, html, re
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree, tostring
from xml.dom import minidom

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from docx import Document
from docx.shared import Inches as DocInches, Pt as DocPt, RGBColor as DocRGB

NAVY = RGBColor(24, 49, 83); BLUE = RGBColor(48, 105, 164); TEAL = RGBColor(25, 130, 130)
PALE = RGBColor(235, 242, 248); LIGHT = RGBColor(247, 249, 251); GREY = RGBColor(92, 107, 122)
WHITE = RGBColor(255,255,255); AMBER = RGBColor(181, 111, 28); RED = RGBColor(170, 65, 65)
TYPE_COLORS = {"user_interface": "#E8F1FB", "application": "#E8F1FB", "service": "#E6F4F1", "database": "#FFF3DF", "external": "#F0ECF8", "queue": "#FCEBEC", "actor": "#F2F4F7"}

def clean(s): return re.sub(r"\s+", " ", str(s or "")).strip()
def status_label(obj):
    st=obj.get("evidence_status", "unknown")
    return "" if st == "confirmed" else f" [{st.upper()}]"
def load_views(model):
    comps={c['id']:c for c in model.get('components',[])}; conns={e['id']:e for e in model.get('connections',[])}
    views=model.get('diagrams') or [{"id":"overview","title":model.get('title','Architecture Overview'),"type":"overview","component_ids":list(comps),"connection_ids":list(conns)}]
    out=[]
    for v in views:
        cids=v.get('component_ids') or list(comps); eids=v.get('connection_ids') or list(conns)
        out.append((v,[comps[x] for x in cids if x in comps],[conns[x] for x in eids if x in conns]))
    return out

def positions(n):
    # Horizontal swimlane-like layout, wrapping to two rows for larger views.
    cols=min(4,max(1,n)); rows=math.ceil(n/cols); pos={}
    for i in range(n): pos[i]=(i%cols, i//cols)
    return pos,cols,rows

def svg_for_view(title, comps, conns, width=1200, height=650):
    margin=70; cols=min(4,max(1,len(comps))); rows=max(1,math.ceil(len(comps)/cols))
    bw=min(230,(width-2*margin-(cols-1)*55)/cols); bh=112
    gapx=(width-2*margin-cols*bw)/(max(1,cols-1)) if cols>1 else 0
    gapy=110; total_h=margin*2+rows*bh+(rows-1)*gapy
    height=max(height,total_h)
    pos={c['id']:(margin+(i%cols)*(bw+gapx), margin+(i//cols)*(bh+gapy)) for i,c in enumerate(comps)}
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
       '<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#526579"/></marker></defs>',
       f'<rect width="100%" height="100%" fill="#F7F9FB"/>',f'<text x="{margin}" y="38" font-family="Aptos,Arial" font-size="24" font-weight="700" fill="#183153">{html.escape(title)}</text>']
    for e in conns:
        if e.get('from') not in pos or e.get('to') not in pos: continue
        x1,y1=pos[e['from']]; x2,y2=pos[e['to']]
        x1+=bw; y1+=bh/2; x2-=8; y2+=bh/2
        if x2 < x1: x1-=bw; x2+=bw+16
        s.append(f'<path d="M{x1},{y1} C{(x1+x2)/2},{y1} {(x1+x2)/2},{y2} {x2},{y2}" fill="none" stroke="#526579" stroke-width="2.2" marker-end="url(#arr)"/>')
        lx=(x1+x2)/2; ly=(y1+y2)/2-9
        edge_no = conns.index(e) + 1
        s.append(f'<circle cx="{lx}" cy="{ly}" r="12" fill="#FFFFFF" stroke="#526579" stroke-width="1.5"/>')
        s.append(f'<text x="{lx}" y="{ly+4}" text-anchor="middle" font-family="Aptos,Arial" font-size="11" font-weight="700" fill="#183153">{edge_no}</text>')
    for c in comps:
        if c['id'] not in pos: continue
        x,y=pos[c['id']]; fill=TYPE_COLORS.get(c.get('type'), '#EAF0F6')
        st=c.get('evidence_status','unknown'); border={'confirmed':'#3069A4','inferred':'#B56F1C','unknown':'#AA4141'}.get(st,'#3069A4')
        name=html.escape(clean(c.get('name'))); typ=html.escape(clean(c.get('type','component')).replace('_',' ').title())
        desc=html.escape(clean(c.get('description'))[:75])
        s.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="12" fill="{fill}" stroke="{border}" stroke-width="2"/>')
        s.append(f'<text x="{x+14}" y="{y+30}" font-family="Aptos,Arial" font-size="17" font-weight="700" fill="#183153">{name}</text>')
        s.append(f'<text x="{x+14}" y="{y+53}" font-family="Aptos,Arial" font-size="12" fill="#526579">{typ}{" · "+st.upper() if st!="confirmed" else ""}</text>')
        s.append(f'<text x="{x+14}" y="{y+77}" font-family="Aptos,Arial" font-size="11" fill="#34495E">{desc}</text>')
    key_y = margin + rows * bh + (rows-1) * gapy + 45
    if conns:
        s.append(f'<text x="{margin}" y="{key_y}" font-family="Aptos,Arial" font-size="14" font-weight="700" fill="#183153">Connection key</text>')
        for j,e in enumerate(conns):
            s.append(f'<text x="{margin}" y="{key_y+24+j*22}" font-family="Aptos,Arial" font-size="12" fill="#34495E">{j+1}. {html.escape(clean(e.get("label")))} — {html.escape(clean(e.get("from")))} → {html.escape(clean(e.get("to")))}</text>')
    s.append('</svg>'); return '\n'.join(s)

def make_pptx(model, views, path):
    prs=Presentation(); prs.slide_width= Inches(13.333); prs.slide_height= Inches(7.5)
    blank=prs.slide_layouts[6]
    # Cover slide
    slide=prs.slides.add_slide(blank); bg=slide.background.fill; bg.solid(); bg.fore_color.rgb=LIGHT
    sh=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,0,0,prs.slide_width, Inches(1.05)); sh.fill.solid(); sh.fill.fore_color.rgb=NAVY; sh.line.fill.background()
    tb=slide.shapes.add_textbox(Inches(.65), Inches(1.75), Inches(12), Inches(1.2)); tf=tb.text_frame; tf.text=model.get('title','Architecture Overview'); tf.paragraphs[0].font.size=Pt(30); tf.paragraphs[0].font.bold=True; tf.paragraphs[0].font.color.rgb=NAVY
    st=slide.shapes.add_textbox(Inches(.68), Inches(2.85), Inches(11.8), Inches(.65)); p=st.text_frame.paragraphs[0]; p.text=model.get('subtitle','Enterprise Architecture'); p.font.size=Pt(17); p.font.color.rgb=GREY
    sm=slide.shapes.add_textbox(Inches(.68), Inches(4.0), Inches(11.7), Inches(1.3)); p=sm.text_frame.paragraphs[0]; p.text=model.get('summary','Architecture visualized from supplied written material.'); p.font.size=Pt(16); p.font.color.rgb=NAVY
    foot=slide.shapes.add_textbox(Inches(.68), Inches(6.85), Inches(11.8), Inches(.3)); p=foot.text_frame.paragraphs[0]; p.text='Generated from a shared architecture model · Editable native PowerPoint elements'; p.font.size=Pt(9); p.font.color.rgb=GREY
    for view, comps, conns in views:
        slide=prs.slides.add_slide(blank); slide.background.fill.solid(); slide.background.fill.fore_color.rgb=LIGHT
        title=slide.shapes.add_textbox(Inches(.45), Inches(.22), Inches(12.3), Inches(.55)); p=title.text_frame.paragraphs[0]; p.text=view.get('title','Architecture view'); p.font.size=Pt(23); p.font.bold=True; p.font.color.rgb=NAVY
        # diagram bounds
        left,top=Inches(.65),Inches(1.25); area_w=Inches(12.0); area_h=Inches(5.25)
        n=max(1,len(comps)); cols=min(4,n); rows=math.ceil(n/cols)
        box_w=min(Inches(2.65), int((area_w-Inches(.45)*(cols-1))/cols)); box_h=Inches(1.05)
        gap_x=(area_w-cols*box_w)/(cols-1) if cols>1 else 0; gap_y=Inches(.8)
        loc={}
        for i,c in enumerate(comps):
            col,row=i%cols,i//cols; x=int(left+col*(box_w+gap_x)); y=int(top+row*(box_h+gap_y)); loc[c['id']]=(x,y)
        # Connectors first, so shapes sit on top
        for e in conns:
            if e.get('from') not in loc or e.get('to') not in loc: continue
            x1,y1=loc[e['from']]; x2,y2=loc[e['to']]
            start=(x1+box_w,y1+box_h//2); end=(x2,y2+box_h//2)
            if end[0] < start[0]: start=(x1,y1+box_h//2); end=(x2+box_w,y2+box_h//2)
            line=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,start[0],start[1],end[0],end[1]); line.line.color.rgb=GREY; line.line.width=Pt(1.8); line.line.end_arrowhead=True
            mx=(start[0]+end[0])//2; my=(start[1]+end[1])//2-Inches(.12)
            edge_no=conns.index(e)+1
            marker=slide.shapes.add_shape(MSO_SHAPE.OVAL,mx-Inches(.12),my-Inches(.12),Inches(.24),Inches(.24))
            marker.fill.solid(); marker.fill.fore_color.rgb=WHITE; marker.line.color.rgb=GREY; marker.line.width=Pt(1)
            mt=marker.text_frame; mt.clear(); mt.vertical_anchor=MSO_ANCHOR.MIDDLE; mt.paragraphs[0].text=str(edge_no); mt.paragraphs[0].font.size=Pt(8); mt.paragraphs[0].font.bold=True; mt.paragraphs[0].font.color.rgb=NAVY; mt.paragraphs[0].alignment=PP_ALIGN.CENTER
        for c in comps:
            if c['id'] not in loc: continue
            x,y=loc[c['id']]; shape=slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,x,y,box_w,box_h)
            shape.fill.solid(); shape.fill.fore_color.rgb={'database':RGBColor(255,243,223),'service':RGBColor(230,244,241),'external':RGBColor(240,236,248),'queue':RGBColor(252,235,236)}.get(c.get('type'),PALE)
            status=c.get('evidence_status','unknown'); shape.line.color.rgb={'confirmed':BLUE,'inferred':AMBER,'unknown':RED}.get(status,BLUE); shape.line.width=Pt(1.5)
            tf=shape.text_frame; tf.clear(); tf.margin_left=Inches(.12); tf.margin_right=Inches(.12); tf.margin_top=Inches(.1); tf.vertical_anchor=MSO_ANCHOR.MIDDLE
            p=tf.paragraphs[0]; p.text=clean(c.get('name'))+status_label(c); p.font.size=Pt(14); p.font.bold=True; p.font.color.rgb=NAVY; p.alignment=PP_ALIGN.CENTER
            p2=tf.add_paragraph(); p2.text=clean(c.get('description'))[:100]; p2.font.size=Pt(9); p2.font.color.rgb=GREY; p2.alignment=PP_ALIGN.CENTER
            p3=tf.add_paragraph(); p3.text=clean(c.get('type','component')).replace('_',' ').title(); p3.font.size=Pt(8); p3.font.color.rgb=BLUE; p3.alignment=PP_ALIGN.CENTER
        # Connection key is kept below the diagram so long labels never collide with shapes.
        if conns:
            key=slide.shapes.add_textbox(Inches(.65), Inches(6.35), Inches(12), Inches(.58))
            kt=key.text_frame; kt.word_wrap=True; kt.clear()
            for j,e in enumerate(conns):
                p=kt.paragraphs[0] if j==0 else kt.add_paragraph(); p.text=f"{j+1}. {clean(e.get('label'))} ({clean(e.get('from'))} → {clean(e.get('to'))})"; p.font.size=Pt(8); p.font.color.rgb=GREY
        # footer legend
        lg=slide.shapes.add_textbox(Inches(.65), Inches(7.05), Inches(12), Inches(.22)); p=lg.text_frame.paragraphs[0]; p.text='Evidence: blue = confirmed   |   amber = inferred   |   red = unknown'; p.font.size=Pt(8); p.font.color.rgb=GREY
    prs.save(path)

def make_drawio(model, views, path):
    mx=Element('mxfile', {'host':'app.diagrams.net','modified':'2026-01-01T00:00:00.000Z','agent':'Architecture Visualizer','version':'24.7.17','type':'device'})
    for vi,(view,comps,conns) in enumerate(views):
        diagram=SubElement(mx,'diagram',{'id':str(view.get('id',f'page-{vi}')),'name':clean(view.get('title',f'Architecture {vi+1}'))})
        model_el=SubElement(diagram,'mxGraphModel',{'dx':'1200','dy':'800','grid':'1','gridSize':'10','guides':'1','tooltips':'1','connect':'1','arrows':'1','fold':'1','page':'1','pageScale':'1','pageWidth':'1200','pageHeight':'850','math':'0','shadow':'0'})
        root=SubElement(model_el,'root'); SubElement(root,'mxCell',{'id':'0'}); SubElement(root,'mxCell',{'id':'1','parent':'0'})
        n=max(1,len(comps)); cols=min(4,n); bw=210; bh=90; gapx=75; gapy=100; pos={}
        for i,c in enumerate(comps):
            x=60+(i%cols)*(bw+gapx); y=80+(i//cols)*(bh+gapy); pos[c['id']]=(x,y)
            cell=SubElement(root,'mxCell',{'id':c['id'],'value':html.escape(clean(c['name'])+status_label(c))+'&#xa;'+html.escape(clean(c.get('description'))),'style':'rounded=1;whiteSpace=wrap;html=1;fillColor='+TYPE_COLORS.get(c.get('type'),'#EAF0F6')+';strokeColor='+({'confirmed':'#3069A4','inferred':'#B56F1C','unknown':'#AA4141'}.get(c.get('evidence_status','unknown')))+';fontColor=#183153;fontSize=14;align=center;verticalAlign=middle;','vertex':'1','parent':'1'})
            SubElement(cell,'mxGeometry',{'x':str(x),'y':str(y),'width':str(bw),'height':str(bh),'as':'geometry'})
        for j,e in enumerate(conns):
            if e.get('from') not in pos or e.get('to') not in pos: continue
            edge=SubElement(root,'mxCell',{'id':e['id'],'value':str(j+1),'style':'edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;strokeColor=#526579;fontSize=11;fontStyle=1;labelBackgroundColor=#FFFFFF;','edge':'1','parent':'1','source':e['from'],'target':e['to']})
            SubElement(edge,'mxGeometry',{'relative':'1','as':'geometry'})
            note_id=f"{e['id']}_label"; note=SubElement(root,'mxCell',{'id':note_id,'value':html.escape(f"{j+1}. {clean(e.get('label'))} ({e.get('from')} → {e.get('to')})"),'style':'text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=11;fontColor=#34495E;','vertex':'1','parent':'1'})
            SubElement(note,'mxGeometry',{'x':'60','y':str(80+math.ceil(len(comps)/cols)*(bh+gapy)+j*24),'width':'900','height':'22','as':'geometry'})
    xml=minidom.parseString(tostring(mx,encoding='utf-8')).toprettyxml(indent='  ',encoding='utf-8')
    path.write_bytes(xml)

def make_svg(model, views, path):
    view,comps,conns=views[0]; path.write_text(svg_for_view(view.get('title',model.get('title','Architecture')),comps,conns),encoding='utf-8')

def make_docx(model, views, svg_path, path):
    png_path = svg_path.with_suffix('.png')
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=1600)
    except Exception as exc:
        png_path = None
        print(f'WARNING: Could not rasterize SVG for Word preview: {exc}')
    doc=Document(); sec=doc.sections[0]; sec.top_margin=DocInches(.65); sec.bottom_margin=DocInches(.65)
    styles=doc.styles; styles['Normal'].font.name='Aptos'; styles['Normal'].font.size=DocPt(10)
    styles['Title'].font.name='Aptos Display'; styles['Title'].font.color.rgb=DocRGB(24,49,83)
    doc.add_heading(model.get('title','Architecture Overview'),0)
    if model.get('subtitle'): doc.add_paragraph(model['subtitle'],style='Subtitle')
    if model.get('summary'): doc.add_heading('Executive summary',1); doc.add_paragraph(model['summary'])
    doc.add_heading('Scope',1)
    for x in model.get('scope',[]): doc.add_paragraph(x,style='List Bullet')
    doc.add_heading('Architecture components',1)
    t=doc.add_table(rows=1, cols=4); t.style='Light Shading Accent 1'
    for cell,txt in zip(t.rows[0].cells,['Component','Type','Responsibility','Evidence']): cell.text=txt
    for c in model.get('components',[]):
        cells=t.add_row().cells; cells[0].text=clean(c.get('name')); cells[1].text=clean(c.get('type')).replace('_',' ').title(); cells[2].text=clean(c.get('description')); cells[3].text=clean(c.get('evidence_status','unknown')).title()
    doc.add_heading('Integrations and connections',1)
    t=doc.add_table(rows=1, cols=5); t.style='Light Shading Accent 1'
    for cell,txt in zip(t.rows[0].cells,['From','To','Interaction','Kind','Evidence']): cell.text=txt
    byid={c['id']:c for c in model.get('components',[])}
    for e in model.get('connections',[]):
        cells=t.add_row().cells; cells[0].text=byid.get(e.get('from'),{}).get('name',e.get('from','')); cells[1].text=byid.get(e.get('to'),{}).get('name',e.get('to','')); cells[2].text=clean(e.get('label')); cells[3].text=clean(e.get('kind','interaction')); cells[4].text=clean(e.get('evidence_status','unknown')).title()
    doc.add_heading('Architecture diagrams',1)
    for i,(v,cs,es) in enumerate(views):
        if i: doc.add_page_break()
        doc.add_heading(v.get('title',f'View {i+1}'),2)
        if i==0 and png_path and png_path.exists(): doc.add_picture(str(png_path),width=DocInches(6.8))
        else: doc.add_paragraph(f"Diagram view: {v.get('type','architecture')}. Refer to the editable PowerPoint and Draw.io files for the full diagram.")
    for title,key in [('Assumptions','assumptions'),('Open questions','open_questions')]:
        doc.add_heading(title,1)
        items=model.get(key,[]) or ['None recorded.']
        for x in items: doc.add_paragraph(x,style='List Bullet')
    doc.add_paragraph('Generated from the shared architecture JSON model. PowerPoint and Draw.io files contain individually editable diagram elements.')
    doc.save(path)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('model',type=Path); ap.add_argument('--out-dir',type=Path,default=Path('architecture-output')); args=ap.parse_args()
    model=json.loads(args.model.read_text(encoding='utf-8')); args.out_dir.mkdir(parents=True,exist_ok=True)
    from validate_model import validate
    errors,warnings=validate(model)
    if errors: raise SystemExit('Model validation failed:\n'+'\n'.join(errors))
    views=load_views(model)
    json_out=args.out_dir/'architecture.json'; json_out.write_text(json.dumps(model,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    svg=args.out_dir/'architecture.svg'; make_svg(model,views,svg)
    pptx=args.out_dir/'architecture.pptx'; make_pptx(model,views,pptx)
    drawio=args.out_dir/'architecture.drawio'; make_drawio(model,views,drawio)
    docx=args.out_dir/'architecture.docx'; make_docx(model,views,svg,docx)
    print('Generated:');
    for p in (pptx,drawio,docx,json_out,svg): print(f' - {p}')
    if warnings:
        print('Warnings:'); [print(' - '+w) for w in warnings]
if __name__=='__main__': main()
