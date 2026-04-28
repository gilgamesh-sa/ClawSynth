#!/usr/bin/env python3
"""Generate e-CNY training PDF using fpdf2."""

from fpdf import FPDF
import os

class PDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('NS', '', 7)
            self.set_text_color(150,150,150)
            self.cell(0, 7, '\u6570\u5b57\u4eba\u6c11\u5e01\uff08e-CNY\uff09\u5458\u5de5\u57f9\u8bad\u8d44\u6599  |  \u7f16\u53f7\uff1aDC-EP-TRN-58372', 0, 1, 'C')
            self.set_draw_color(200,200,200)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(3)

    def footer(self):
        if self.page_no() > 1:
            self.set_y(-15)
            self.set_font('NS', '', 7)
            self.set_text_color(150,150,150)
            self.cell(0, 10, '\u7b2c %d \u9875' % self.page_no(), 0, 0, 'C')

    def h2(self, t):
        self.set_font('NR', 'B', 14)
        self.set_text_color(44, 62, 80)
        self.cell(0, 10, t, 0, 1, 'L')
        self.set_draw_color(192, 57, 43)
        self.set_line_width(0.7)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def h3(self, t):
        self.set_font('NS', 'B', 10.5)
        self.set_text_color(41, 128, 185)
        self.cell(0, 8, t, 0, 1, 'L')
        self.ln(1)

    def body(self, t):
        self.set_font('NS', '', 9)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5.2, t)
        self.ln(2)

    def table_header(self, headers, widths):
        self.set_font('NS', 'B', 7.5)
        self.set_fill_color(44, 62, 80)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(widths[i], 7, h, 1, 0, 'C', True)
        self.ln()

    def table_row(self, cells, widths, bold=False, highlight=False):
        if self.get_y() > 262:
            self.add_page()
        self.set_text_color(30, 30, 30)
        if highlight:
            self.set_fill_color(254, 249, 231)
            self.set_font('NS', 'B', 7.5)
        elif bold:
            self.set_font('NS', 'B', 7.5)
        else:
            self.set_font('NS', '', 7.5)
        for i, c in enumerate(cells):
            self.cell(widths[i], 6, c, 1, 0, 'C' if i >= 1 else 'L', highlight)
        self.ln()

    def fbox(self, title, lines):
        self.set_fill_color(254, 249, 231)
        self.set_draw_color(240, 192, 64)
        bh = 5 + len(lines) * 4.8 + 2
        if self.get_y() + bh > 268:
            self.add_page()
        y0 = self.get_y()
        self.rect(10, y0, 190, bh, 'DF')
        self.set_fill_color(243, 156, 18)
        self.rect(10, y0, 1.5, bh, 'F')
        self.set_xy(14, y0 + 1.5)
        self.set_font('NS', 'B', 8.5)
        self.set_text_color(183, 149, 11)
        self.cell(0, 5, title, 0, 1)
        self.set_font('NS', '', 8)
        self.set_text_color(51, 51, 51)
        for ln in lines:
            self.set_x(14)
            self.cell(0, 4.8, ln, 0, 1)
        self.set_y(y0 + bh + 2)

    def note_box(self, title, lines, color=(39,174,96)):
        self.set_fill_color(234, 250, 241)
        self.set_draw_color(*color)
        bh = 5 + len(lines) * 4.5 + 1
        if self.get_y() + bh > 268:
            self.add_page()
        y0 = self.get_y()
        self.rect(10, y0, 190, bh, 'DF')
        self.set_fill_color(*color)
        self.rect(10, y0, 1.5, bh, 'F')
        self.set_xy(14, y0 + 1.5)
        self.set_font('NS', 'B', 8)
        self.set_text_color(30, 132, 73)
        self.cell(0, 5, title, 0, 1)
        self.set_font('NS', '', 7.5)
        self.set_text_color(60, 60, 60)
        for ln in lines:
            self.set_x(14)
            self.cell(0, 4.5, ln, 0, 1)
        self.set_y(y0 + bh + 3)


pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=20)

# Fonts
pdf.add_font('NS', '', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', uni=True)
pdf.add_font('NS', 'B', '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', uni=True)
pdf.add_font('NR', '', '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', uni=True)
pdf.add_font('NR', 'B', '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc', uni=True)

# ===================== COVER =====================
pdf.add_page()
pdf.ln(55)
pdf.set_font('NR', 'B', 24)
pdf.set_text_color(192, 57, 43)
pdf.cell(0, 14, '\u6570\u5b57\u4eba\u6c11\u5e01\uff08e-CNY\uff09', 0, 1, 'C')
pdf.ln(3)
pdf.set_font('NR', 'B', 16)
pdf.set_text_color(44, 62, 80)
pdf.cell(0, 12, '\u5458\u5de5\u57f9\u8bad\u8d44\u6599', 0, 1, 'C')
pdf.ln(4)
pdf.set_font('NS', '', 10)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 7, 'Digital Currency Electronic Payment \u2014 Internal Training Guide', 0, 1, 'C')
pdf.ln(12)
pdf.set_font('NS', '', 9)
pdf.set_text_color(160, 160, 160)
pdf.cell(0, 6, '\u7248\u672c\uff1aV2.0    |    \u5bc6\u7ea7\uff1a\u5185\u90e8\u8d44\u6599    |    \u7f16\u53f7\uff1aDC-EP-TRN-58372', 0, 1, 'C')
pdf.cell(0, 6, '\u7f16\u5236\u90e8\u95e8\uff1a\u91d1\u878d\u79d1\u6280\u57f9\u8bad\u4e2d\u5fc3    |    \u65e5\u671f\uff1a2025\u5e747\u6708', 0, 1, 'C')
pdf.ln(45)
pdf.set_font('NS', '', 8)
pdf.set_text_color(180, 180, 180)
pdf.cell(0, 5, '\u672c\u8d44\u6599\u4ec5\u4f9b\u5185\u90e8\u57f9\u8bad\u4f7f\u7528\uff0c\u672a\u7ecf\u6388\u6743\u4e0d\u5f97\u5916\u4f20', 0, 1, 'C')

# ===================== TOC =====================
pdf.add_page()
pdf.h2('\u76ee  \u5f55')
pdf.set_font('NS', '', 10)
pdf.set_text_color(44, 62, 80)
for t in ['\u4e00\u3001\u6838\u5fc3\u6982\u5ff5\u89e3\u6790', '\u4e8c\u3001\u4e3b\u8981\u529f\u80fd\u6a21\u5757', '\u4e09\u3001\u5178\u578b\u4f7f\u7528\u573a\u666f', '\u56db\u3001\u5173\u952e\u65f6\u95f4\u8282\u70b9\uff08\u8bd5\u70b9\u2192\u5168\u9762\u63a8\u5e7f\uff09', '\u4e94\u3001\u8bd5\u70b9\u57ce\u5e02\u63a8\u5e7f\u6570\u636e\u5bf9\u6bd4\u8868', '\u516d\u3001\u6c47\u603b\u7edf\u8ba1\u516c\u5f0f', '\u4e03\u3001\u9644\u5f55\uff1a\u5e38\u89c1\u95ee\u9898\uff08FAQ\uff09']:
    pdf.cell(0, 8, t, 0, 1)

# ===================== SECTION 1 =====================
pdf.add_page()
pdf.h2('\u4e00\u3001\u6838\u5fc3\u6982\u5ff5\u89e3\u6790')
pdf.body('\u6570\u5b57\u4eba\u6c11\u5e01\u662f\u4e2d\u56fd\u4eba\u6c11\u94f6\u884c\u53d1\u884c\u7684\u6cd5\u5b9a\u6570\u5b57\u8d27\u5e01\uff0c\u5177\u6709\u56fd\u5bb6\u4fe1\u7528\u80cc\u4e66\u3001\u6cd5\u5f8b\u6548\u529b\u7b49\u540c\u73b0\u91d1\u7684\u7279\u5f81\u3002')

concepts = [
    ['\u6570\u5b57\u4eba\u6c11\u5e01(e-CNY)', '\u592e\u884c\u53d1\u884c\u7684\u6cd5\u5b9a\u6570\u5b57\u8d27\u5e01\uff0c\u6570\u5b57\u5f62\u5f0f\u7684M0\uff0c\u5177\u6709\u4ef7\u503c\u7279\u5f81\u548c\u6cd5\u507f\u6027\u3002', '\u6cd5\u5b9a\u8d27\u5e01|M0\u5c42\u7ea7|\u56fd\u5bb6\u4fe1\u7528'],
    ['\u53cc\u5c42\u8fd0\u8425\u4f53\u7cfb(Two-tier)', '\u592e\u884c\u2192\u8fd0\u8425\u673a\u6784(\u5de5\u519c\u4e2d\u5efa\u4ea4\u90ae\u50a8)\u2192\u516c\u4f17\u3002\u592e\u884c\u8d1f\u8d23\u53d1\u884c\u56de\u7b3c\u3002', '\u592e\u884c-\u5546\u4e1a\u94f6\u884c|\u907f\u514d\u76f4\u8fde'],
    ['\u53ef\u63a7\u533f\u540d(Controllable Anon.)', '\u5c0f\u989d\u652f\u4ed8\u533f\u540d\u4fdd\u62a4\u9690\u79c1\uff0c\u5927\u989d\u4ea4\u6613\u4f9d\u6cd5\u53ef\u8ffd\u6eaf\u3002', '\u5c0f\u989d\u533f\u540d|\u5927\u989d\u53ef\u63a7'],
    ['\u6570\u5b57\u94b1\u5305(Digital Wallet)', '\u5206\u56db\u7c7b(\u4e00\u81f3\u56db\u7c7b)\uff0c\u7b49\u7ea7\u8d8a\u9ad8\u529f\u80fd\u8d8a\u5168\u3001\u989d\u5ea6\u8d8a\u5927\u3002', '\u56db\u7ea7\u94b1\u5305|\u5206\u7ea7\u7ba1\u7406'],
    ['\u53cc\u79bb\u7ebf\u652f\u4ed8(Offline Payment)', '\u65e0\u7f51\u7edc\u4e0b\u78b0\u4e00\u78b0\u652f\u4ed8\uff0c\u8054\u7f51\u540e\u81ea\u52a8\u540c\u6b65\u3002', '\u65e0\u7f51\u652f\u4ed8|NFC\u6280\u672f'],
    ['\u667a\u80fd\u5408\u7ea6(Smart Contract)', '\u5d4c\u5165\u53ef\u7f16\u7a0b\u811a\u672c\uff0c\u5b9e\u73b0\u5b9a\u5411\u652f\u4ed8\u3001\u6761\u4ef6\u652f\u4ed8\u3001\u81ea\u52a8\u5206\u8d26\u3002', '\u53ef\u7f16\u7a0b|\u6761\u4ef6\u89e6\u53d1'],
    ['\u5151\u6362/\u56de\u7b3c(Mint/Redeem)', '\u8fd0\u8425\u673a\u6784\u4ece\u592e\u884c\u83b7\u53d6e-CNY\u4e3a\u5151\u6362\uff0c\u6362\u56de\u5b58\u6b3e\u4e3a\u56de\u7b3c\u3002', '1:1\u7b49\u4ef7|\u65e0\u5229\u606f'],
    ['\u6cd5\u507f\u6027(Legal Tender)', '\u4efb\u4f55\u5355\u4f4d\u548c\u4e2a\u4eba\u4e0d\u5f97\u62d2\u6536\uff0c\u4e0e\u4eba\u6c11\u5e01\u73b0\u91d1\u540c\u6cd5\u5f8b\u5730\u4f4d\u3002', '\u5f3a\u5236\u63a5\u53d7|\u6cd5\u5f8b\u4fdd\u969c'],
]
cw1 = [36, 98, 56]
pdf.table_header(['\u6982\u5ff5\u540d\u79f0', '\u5b9a\u4e49\u8bf4\u660e', '\u5173\u952e\u7279\u5f81'], cw1)
for r in concepts:
    pdf.table_row(r, cw1)

# ===================== SECTION 2 =====================
pdf.add_page()
pdf.h2('\u4e8c\u3001\u4e3b\u8981\u529f\u80fd\u6a21\u5757')
pdf.body('\u6570\u5b57\u4eba\u6c11\u5e01 App \u4e3a\u7528\u6237\u63d0\u4f9b\u5b8c\u6574\u7684\u652f\u4ed8\u4e0e\u91d1\u878d\u670d\u52a1\u5165\u53e3\u3002')

funcs = [
    ['1', '\u94b1\u5305\u7ba1\u7406', '\u5f00\u7acb\u3001\u5347\u7ea7\u3001\u6ce8\u9500\u94b1\u5305\uff1b\u591a\u94b1\u5305\u7ba1\u7406', '\u5168\u7b49\u7ea7', '\u5bc6\u7801\u5b66\u5bc6\u94a5\u5bf9'],
    ['2', '\u626b\u7801\u652f\u4ed8', '\u4e3b\u626b/\u88ab\u626b\u4ed8\u6b3e\uff0c\u652f\u6301\u5546\u6237\u4e8c\u7ef4\u7801', '\u5168\u7b49\u7ea7', 'QR\u7801+TLS\u52a0\u5bc6'],
    ['3', '\u53cc\u79bb\u7ebf\u652f\u4ed8', '\u65e0\u7f51\u7edc\u78b0\u4e00\u78b0\u652f\u4ed8\uff08NFC\uff09', '\u4e8c\u7c7b\u53ca\u4ee5\u4e0a', 'NFC+\u533f\u540d\u5238'],
    ['4', '\u8f6c\u8d26\u6c47\u6b3e', '\u94b1\u5305\u95f4\u5b9e\u65f6\u8f6c\u8d26\uff0c\u624b\u673a\u53f7/ID\u4e92\u8f6c', '\u4e8c\u7c7b\u53ca\u4ee5\u4e0a', 'DCEP\u534f\u8bae'],
    ['5', '\u5145\u5151/\u63d0\u73b0', '\u94f6\u884c\u5361\u5145\u503c/\u63d0\u73b0\u81f3\u94b6\u884c\u5361', '\u4e8c\u7c7b\u53ca\u4ee5\u4e0a', 'API\u5bf9\u63a5'],
    ['6', '\u667a\u80fd\u5408\u7ea6', '\u5b9a\u5411\u652f\u4ed8\u3001\u9884\u4ed8\u5361\u3001\u8865\u8d34\u53d1\u653e', '\u4e8c\u7c7b\u53ca\u4ee5\u4e0a', 'Lua\u811a\u672c'],
    ['7', '\u7ea2\u5305/\u6d88\u8d39\u5238', '\u53d1\u653e\u9886\u53d6\u7ea2\u5305\u6d88\u8d39\u5238', '\u5168\u7b49\u7ea7', '\u667a\u80fd\u5408\u7ea6'],
    ['8', '\u8de8\u5883\u652f\u4ed8', 'mBridge\u591a\u8fb9\u592e\u884c\u8de8\u5883\u7ed3\u7b97', '\u4e8c\u7c7b\u53ca\u4ee5\u4e0a', 'mBridge\u5e73\u53f0'],
    ['9', '\u786c\u94b1\u5305', '\u53ef\u89c6\u5361\u3001\u624b\u73af\u3001NFC-SIM', '\u5168\u7b49\u7ea7', 'SE\u5b89\u5168\u82af\u7247'],
    ['10', '\u8d26\u6237\u67e5\u8be2', '\u6d41\u6c34\u3001\u4f59\u989d\u67e5\u8be2\u3001\u5bfc\u51fa\u8d26\u5355', '\u5168\u7b49\u7ea7', '\u672c\u5730+\u4e91\u7aef'],
]
fw1 = [8, 22, 74, 22, 24]
pdf.table_header(['\u5e8f\u53f7', '\u529f\u80fd\u6a21\u5757', '\u529f\u80fd\u63cf\u8ff0', '\u94b1\u5305\u7b49\u7ea7', '\u6280\u672f\u5b9e\u73b0'], fw1)
for r in funcs:
    pdf.table_row(r, fw1)

pdf.ln(5)
pdf.h3('\u94b1\u5305\u7b49\u7ea7\u4e0e\u989d\u5ea6\u5bf9\u7167')
wt = [20, 50, 28, 28, 28]
pdf.table_header(['\u94b1\u5305\u7b49\u7ea7', '\u5f00\u901a\u6761\u4ef6', '\u5355\u7b14\u9650\u989d', '\u65e5\u7d2f\u8ba1\u9650\u989d', '\u4f59\u989d\u4e0a\u9650'], wt)
for r in [
    ['\u56db\u7c7b', '\u624b\u673a\u53f7\u5373\u53ef\u5f00\u901a', '2,000\u5143', '5,000\u5143', '10,000\u5143'],
    ['\u4e09\u7c7b', '\u8eab\u4efd\u8bc1+\u624b\u673a\u53f7', '5,000\u5143', '50,000\u5143', '20,000\u5143'],
    ['\u4e8c\u7c7b', '\u5b9e\u540d\u8ba4\u8bc1+\u7ed1\u5b9aI\u7c7b\u8d26\u6237', '50,000\u5143', '50,000\u5143', '500,000\u5143'],
    ['\u4e00\u7c7b', '\u9762\u5bf9\u9762\u67dc\u53f0/\u7f51\u70b9\u529e\u7406', '500,000\u5143', '500,000\u5143', '\u65e0\u4e0a\u9650'],
]:
    pdf.table_row(r, wt)

# ===================== SECTION 3 =====================
pdf.add_page()
pdf.h2('\u4e09\u3001\u5178\u578b\u4f7f\u7528\u573a\u666f')
pdf.body('\u6570\u5b57\u4eba\u6c11\u5e01\u5df2\u5728\u653f\u52a1\u3001\u96f6\u552e\u3001\u4ea4\u901a\u3001\u6587\u65c5\u3001\u666e\u60e0\u91d1\u878d\u7b49\u591a\u9886\u57df\u843d\u5730\u3002')

scenes = [
    ['1', '\u65e5\u5e38\u6d88\u8d39', '\u8d85\u5e02\u3001\u9910\u996e\u3001\u4fbf\u5229\u5e97\u3001\u83dc\u5e02\u573a', '\u96f6\u624b\u7eed\u8d39\u5373\u65f6\u5230\u8d26', '\u6df1\u5733\u82cf\u5dde\u7ea2\u5305'],
    ['2', '\u516c\u5171\u4ea4\u901a', '\u516c\u4ea4\u3001\u5730\u94c1\u3001\u9ad8\u901fETC', '\u53cc\u79bb\u7ebf\u78b0\u4e00\u78b0', '\u5317\u4eac\u5730\u94c1'],
    ['3', '\u653f\u52a1\u7f34\u8d39', '\u7a0e\u8d39\u3001\u793e\u4fdd\u3001\u516c\u79ef\u91d1', '\u8d44\u91d1\u76f4\u8fbe\u56fd\u5e93', '\u6d77\u5357\u7a0e\u52a1'],
    ['4', '\u5de5\u8d44/\u8865\u8d34', '\u8d22\u653f\u8865\u8d34\u3001\u5de5\u8d44\u3001\u6d88\u8d39\u5238', '\u667a\u80fd\u5408\u7ea6\u5b9a\u5411\u53d1\u653e', '\u96c4\u5b89\u65b0\u533a'],
    ['5', '\u666e\u60e0\u91d1\u878d', '\u65e0\u94f6\u884c\u8d26\u6237\u4eba\u7fa4\u5f00\u6237', '\u624b\u673a\u53f7\u5373\u5f00\u56db\u7c7b\u94b1\u5305', '\u5927\u51c9\u5c71\u8bd5\u70b9'],
    ['6', '\u9884\u4ed8\u6d88\u8d39', '\u6559\u57f9\u3001\u5065\u8eab\u3001\u7f8e\u5bb9\u9884\u4ed8\u5361', '\u667a\u80fd\u5408\u7ea6\u9632\u8dd1\u8def', '\u5317\u4eac\u6559\u57f9'],
    ['7', '\u8de8\u5883\u652f\u4ed8', '\u8de8\u5883\u8d38\u6613\u3001\u65c5\u6e38\u3001\u6c47\u6b3e', 'mBridge\u79d2\u7ea7\u7ed3\u7b97', '\u591a\u8fb9\u8d27\u5e01\u6865'],
    ['8', '\u4f9b\u5e94\u94fe\u91d1\u878d', '\u4f01\u4e1a\u7ed3\u7b97\u3001\u7968\u636e\u878d\u8d44', '\u81ea\u52a8\u5206\u8d26\u63d0\u6548\u7387', '\u82cf\u5dde\u5de5\u4e1a\u56ed'],
    ['9', '\u6587\u65c5\u6d88\u8d39', '\u666f\u533a\u95e8\u7968\u3001\u9152\u5e97\u3001\u6587\u521b', '\u6d88\u8d39\u5238\u7cbe\u51c6\u6295\u653e', '\u6210\u90fd\u897f\u5b89'],
    ['10', '\u7535\u5b50\u5546\u52a1', '\u4eac\u4e1c\u3001\u7f8e\u56e2\u3001\u6dd8\u5b9d\u7ebf\u4e0a\u8d2d\u7269', '\u8de8\u5e73\u53f0\u901a\u7528', '\u4eac\u4e1c\u7f8e\u56e2\u63a5\u5165'],
]
sw = [8, 20, 52, 50, 26]
pdf.table_header(['\u5e8f\u53f7', '\u573a\u666f\u7c7b\u522b', '\u5177\u4f53\u573a\u666f', 'e-CNY\u4f18\u52bf', '\u8bd5\u70b9\u6848\u4f8b'], sw)
for r in scenes:
    pdf.table_row(r, sw)

# ===================== SECTION 4 =====================
pdf.add_page()
pdf.h2('\u56db\u3001\u5173\u952e\u65f6\u95f4\u8282\u70b9\uff08\u8bd5\u70b9\u2192\u5168\u9762\u63a8\u5e7f\uff09')
pdf.body('\u68b3\u7406\u6570\u5b57\u4eba\u6c11\u5e01\u4ece\u7814\u7a76\u7acb\u9879\u5230\u5168\u56fd\u63a8\u5e7f\u7684\u5173\u952e\u91cc\u7a0b\u7891\u3002')

tl = [
    ['2014\u5e74', '\u7814\u7a76\u542f\u52a8', '\u592e\u884c\u6210\u7acb\u6cd5\u5b9a\u6570\u5b57\u8d27\u5e01\u7814\u7a76\u5c0f\u7ec4\uff0c\u5f00\u542f\u7406\u8bba\u7814\u7a76\u548c\u6280\u672f\u8bba\u8bc1\u3002'],
    ['2016\u5e741\u6708', '\u7814\u7a76\u6240\u7b79\u5907', '\u592e\u884c\u53ec\u5f00\u6570\u5b57\u8d27\u5e01\u7814\u8ba8\u4f1a\uff0c\u660e\u786e\u6218\u7565\u76ee\u6807\u548c\u5b9e\u65bd\u8def\u5f84\u3002'],
    ['2017\u5e74', '\u7814\u7a76\u6240\u6210\u7acb', '\u4eba\u6c11\u94f6\u884c\u6570\u5b57\u8d27\u5e01\u7814\u7a76\u6240\u6302\u724c\u6210\u7acb\u3002'],
    ['2019\u5e74\u5e95', '\u5c01\u95ed\u6d4b\u8bd5', '\u6df1\u5733\u3001\u82cf\u5dde\u3001\u96c4\u5b89\u3001\u6210\u90fd\u542f\u52a8\u5c0f\u8303\u56f4\u5c01\u95ed\u8bd5\u70b9\u6d4b\u8bd5\u3002'],
    ['2020.10', '\u6df1\u5733\u516c\u6d4b', '\u53d1\u653e1,000\u4e07\u5143\u7ea2\u5305(5\u4e07\u4efd\u00d7200\u5143)\uff0c\u9996\u6b21\u9762\u5411\u516c\u4f17\u3002'],
    ['2020.12', '\u82cf\u5dde\u7ea2\u5305', '\u201c\u53cc\u5341\u4e8c\u201d\u53d1\u653e2,000\u4e07\u5143\uff0c\u9996\u6b21\u6d4b\u8bd5\u7ebf\u4e0a\u7535\u5546\u3002'],
    ['2021.02', '\u51ac\u5965\u573a\u666f', '\u6d4b\u8bd5\u8de8\u5883\u652f\u4ed8\u3001\u53cc\u79bb\u7ebf\u3001\u786c\u94b1\u5305\u7b49\u529f\u80fd\u3002'],
    ['2021.06-07', '\u7b2c\u4e8c\u6279\u8bd5\u70b9', '\u6269\u5c55\u81f3\u4e0a\u6d77\u3001\u6d77\u5357\u3001\u957f\u6c99\u3001\u897f\u5b89\u3001\u9752\u5c9b\u3001\u5927\u8fde\u3002'],
    ['2022.01', '\u51ac\u5965\u4f1a\u5e94\u7528', '\u9762\u5411\u5916\u7c4d\u8fd0\u52a8\u5458\u63d0\u4f9b\u786c\u94b1\u5305\u548c\u8de8\u5883\u652f\u4ed8\u670d\u52a1\u3002'],
    ['2022.12', '\u5927\u89c4\u6a21\u6269\u5c55', '\u8bd5\u70b9\u6269\u81f3\u5e7f\u4e1c\u3001\u6c5f\u82cf\u3001\u6cb3\u5317\u3001\u56db\u5ddd\u5168\u7701\u53ca\u591a\u57ce\u5e02\u3002'],
    ['2023.04', '\u5168\u57df\u8bd5\u70b9', '\u65b0\u589e\u5929\u6d25\u3001\u91cd\u5e86\u7b49\uff0c\u8bd5\u70b9\u5730\u533a\u7d2f\u8ba1\u8fbe26\u4e2a\u3002'],
    ['2023.07', 'App\u4e0a\u67b6', '\u6570\u5b57\u4eba\u6c11\u5e01App\u4e0a\u67b6\u5404\u5927\u5e94\u7528\u5546\u5e97\uff0c\u5168\u56fd\u53ef\u4e0b\u8f7d\u3002'],
    ['2023.09', '\u652f\u4ed8\u5b9d\u5fae\u4fe1\u63a5\u5165', '\u652f\u4ed8\u5b9d\u548c\u5fae\u4fe1\u652f\u4ed8\u6b63\u5f0f\u652f\u6301\u6570\u5b57\u4eba\u6c11\u5e01\u4e92\u901a\u3002'],
    ['2024\u5e74', '\u6301\u7eed\u63a8\u5e7f', '17\u4e2a\u7701\u5e02\u5168\u57df\u8bd5\u70b9\uff1bmBridge\u8fdb\u5165MVP\uff1b\u4ea4\u6613\u989d\u78017\u4e07\u4ebf\u3002'],
    ['2025\u5e74(\u5c55\u671b)', '\u5168\u9762\u6df1\u5316', '\u63a8\u8fdb\u5168\u56fd\u5e94\u7528\uff0c\u6df1\u5316\u8de8\u5883\u652f\u4ed8\uff0c\u4e30\u5bcc\u667a\u80fd\u5408\u7ea6\u751f\u6001\u3002'],
]
tw = [24, 26, 140]
pdf.table_header(['\u65f6\u95f4', '\u4e8b\u4ef6', '\u8be6\u7ec6\u5185\u5bb9'], tw)
for r in tl:
    pdf.table_row(r, tw)

# ===================== SECTION 5 =====================
pdf.add_page()
pdf.h2('\u4e94\u3001\u8bd5\u70b9\u57ce\u5e02\u63a8\u5e7f\u6570\u636e\u5bf9\u6bd4\u8868')
pdf.body('\u4ee5\u4e0b\u6570\u636e\u7efc\u5408\u592e\u884c\u516c\u5f00\u62a5\u544a\u53ca\u5404\u8bd5\u70b9\u5730\u533a\u62ab\u9732\u4fe1\u606f\u6574\u7406\uff08\u622a\u81f32025\u5e74\u521d\uff0c\u90e8\u5206\u4e3a\u884c\u4e1a\u4f30\u7b97\u503c\uff09\u3002')

cd = [
    ['\u8bd5\u70b9\u57ce\u5e02', '\u542f\u52a8\u65f6\u95f4', '\u94b1\u5305\u6570(\u4e07\u6237)', '\u4ea4\u6613\u989d(\u4ebf\u5143)', '\u4ea4\u6613\u7b14\u6570(\u4e07\u7b14)', '\u6d3b\u8dc3\u5546\u6237(\u4e07\u6237)', '\u7ea2\u5305\u53d1\u653e(\u4ebf\u5143)', '\u6708\u5747\u589e\u957f'],
    ['\u6df1\u5733', '2020.10', '3,200', '8,500', '125,000', '86', '6.8', '5.2%'],
    ['\u82cf\u5dde', '2020.12', '2,800', '6,200', '98,000', '72', '5.5', '4.8%'],
    ['\u96c4\u5b89\u65b0\u533a', '2019.12', '420', '1,800', '22,000', '12', '2.0', '6.1%'],
    ['\u6210\u90fd', '2019.12', '2,600', '5,500', '88,000', '65', '4.2', '4.5%'],
    ['\u5317\u4eac', '2021.02', '3,500', '9,800', '150,000', '95', '7.5', '4.9%'],
    ['\u4e0a\u6d77', '2021.06', '3,100', '7,600', '118,000', '82', '5.8', '5.0%'],
    ['\u5e7f\u5dde', '2021.04', '2,400', '5,100', '82,000', '58', '4.0', '4.6%'],
    ['\u6d77\u5357', '2021.06', '980', '2,600', '35,000', '22', '3.2', '5.5%'],
    ['\u957f\u6c99', '2021.06', '1,500', '3,200', '52,000', '35', '2.5', '4.3%'],
    ['\u897f\u5b89', '2021.06', '1,350', '2,800', '45,000', '30', '2.8', '4.7%'],
]
cdw = [22, 18, 22, 22, 26, 22, 22, 18]
pdf.table_header(cd[0], cdw)
for r in cd[1:]:
    pdf.table_row(r, cdw)

pdf.ln(3)
pdf.note_box('\u6570\u636e\u8bf4\u660e', [
    '1. \u4ee5\u4e0a\u6570\u636e\u622a\u81f32025\u5e74\u521d\uff0c\u7efc\u5408\u592e\u884c\u5de5\u4f5c\u8bba\u6587\u3001\u5730\u65b9\u653f\u5e9c\u62a5\u544a\u53ca\u884c\u4e1a\u7814\u7a76\u673a\u6784\u62ab\u9732\u6570\u636e\u6574\u7406\u3002\u90e8\u5206\u6570\u636e\u4e3a\u884c\u4e1a\u5408\u7406\u4f30\u7b97\u3002',
    '2. \u201c\u6708\u5747\u589e\u957f\u7387\u201d\u6307\u94b1\u5305\u5f00\u7acb\u6570\u91cf\u7684\u590d\u5408\u6708\u5747\u589e\u957f\u767e\u5206\u6bd4\u3002',
])

# ===================== SECTION 6 =====================
pdf.add_page()
pdf.h2('\u516d\u3001\u6c47\u603b\u7edf\u8ba1\u516c\u5f0f')
pdf.body('\u4ee5\u4e0b\u516c\u5f0f\u7528\u4e8e\u5bf9\u6bd4\u5404\u8bd5\u70b9\u57ce\u5e02\u7684\u63a8\u5e7f\u6570\u636e\uff0c\u57f9\u8bad\u4e2d\u53ef\u7ed3\u5408 Excel \u8fdb\u884c\u5b9e\u9645\u6f14\u7ec3\u3002')

pdf.h3('6.1 \u57fa\u7840\u6c47\u603b\u516c\u5f0f')

pdf.fbox('\u516c\u5f0f 1\uff1a\u7d2f\u8ba1\u94b1\u5305\u603b\u6570\uff08\u5168\u8bd5\u70b9\u57ce\u5e02\uff09', [
    'W_total = \u03a3 Wi  (i = 1, 2, ..., n)',
    '\u793a\u4f8b\uff1a3,200+2,800+420+2,600+3,500+3,100+2,400+980+1,500+1,350 = 21,850 \u4e07\u6237',
    'Excel\uff1a=SUM(B2:B11)',
])

pdf.fbox('\u516c\u5f0f 2\uff1a\u7d2f\u8ba1\u4ea4\u6613\u603b\u989d', [
    'T_total = \u03a3 Ti  (i = 1, 2, ..., n)',
    '\u793a\u4f8b\uff1a8,500+6,200+1,800+5,500+9,800+7,600+5,100+2,600+3,200+2,800 = 53,100 \u4ebf\u5143',
    'Excel\uff1a=SUM(C2:C11)',
])

pdf.fbox('\u516c\u5f0f 3\uff1a\u7d2f\u8ba1\u4ea4\u6613\u603b\u7b14\u6570', [
    'P_total = \u03a3 Pi  (i = 1, 2, ..., n)',
    '\u793a\u4f8b\uff1a125,000+98,000+22,000+88,000+150,000+118,000+82,000+35,000+52,000+45,000 = 815,000 \u4e07\u7b14',
    'Excel\uff1a=SUM(D2:D11)',
])

pdf.fbox('\u516c\u5f0f 4\uff1a\u5404\u57ce\u5e02\u5e73\u5747\u94b1\u5305\u6570', [
    'W_avg = W_total / n',
    '\u793a\u4f8b\uff1a21,850 / 10 = 2,185 \u4e07\u6237/\u57ce\u5e02',
    'Excel\uff1a=AVERAGE(B2:B11)',
])

pdf.h3('6.2 \u63a8\u5e7f\u6548\u7387\u5bf9\u6bd4\u516c\u5f0f')

pdf.fbox('\u516c\u5f0f 5\uff1a\u7b14\u5747\u4ea4\u6613\u91d1\u989d', [
    'ATVi = Ti / Pi  (\u4e07\u5143/\u7b14)',
    '\u793a\u4f8b(\u6df1\u5733)\uff1a8,500 / 125,000 = 0.068 \u4e07\u5143/\u7b14 = 680 \u5143/\u7b14',
    'Excel\uff1a=C2/D2',
])

pdf.fbox('\u516c\u5f0f 6\uff1a\u63a8\u5e7f\u6548\u7387\u6307\u6570\uff08\u5355\u4f4d\u94b1\u5305\u4ea4\u6613\u989d\uff09', [
    'EII = Ti / Wi  (\u4e07\u5143/\u4e07\u6237\u94b1\u5305)',
    '\u793a\u4f8b(\u6df1\u5733)\uff1a8,500 / 3,200 = 2.66 \u4e07\u5143/\u4e07\u6237\uff08EI\u8d8a\u9ad8\u6d3b\u8dc3\u5ea6\u8d8a\u9ad8\uff09',
    'Excel\uff1a=C2/B2',
])

pdf.fbox('\u516c\u5f0f 7\uff1a\u7ea2\u5305\u62c9\u52a8\u6548\u5e94', [
    'LBi = Ti / Bi  (\u6bcf\u5143\u7ea2\u5305\u6492\u52a8\u7684\u4ea4\u6613\u989d)',
    '\u793a\u4f8b(\u5317\u4eac)\uff1a9,800 / 7.5 = 1,306.7 \u500d\uff08\u6bcf\u53d11\u5143\u62c9\u52a8\u7ea61,307\u5143\u4ea4\u6613\uff09',
    'Excel\uff1a=C2/G2',
])

pdf.fbox('\u516c\u5f0f 8\uff1a\u5546\u6237\u8986\u76d6\u7387', [
    'MCi = Mi / Wi \u00d7 10,000  (\u5546\u6237\u6570/\u4e07\u6237\u94b1\u5305)',
    '\u793a\u4f8b(\u5317\u4eac)\uff1a95 / 3,500 \u00d7 10,000 = 271.4 \u6237/\u4e07\u6237',
    'Excel\uff1a=F2/B2*10000',
])

pdf.h3('6.3 \u7efc\u5408\u8bc4\u5206\u516c\u5f0f\uff08\u52a0\u6743\u6a21\u578b\uff09')

pdf.fbox('\u516c\u5f0f 9\uff1a\u8bd5\u70b9\u57ce\u5e02\u7efc\u5408\u63a8\u5e7f\u8bc4\u5206', [
    'Score = 0.25\u00d7(Wi/Wmax) + 0.25\u00d7(Ti/Tmax) + 0.20\u00d7(Pi/Pmax)',
    '       + 0.15\u00d7(EIi/EImax) + 0.15\u00d7(LBi/LBmax)',
    '\u6743\u91cd\uff1a\u94b1\u5305\u657025% | \u4ea4\u6613\u989d25% | \u4ea4\u6613\u7b14\u657020% | \u63a8\u5e7f\u6548\u738715% | \u62c9\u52a8\u6548\u5e9415%',
    'Excel\uff1a=0.25*(B2/MAX($B$2:$B$11))+0.25*(C2/MAX($C$2:$C$11))',
    '      +0.2*(D2/MAX($D$2:$D$11))+0.15*((C2/B2)/MAX($C$2:$C$11/$B$2:$B$11))',
    '      +0.15*((C2/G2)/MAX($C$2:$C$11/$G$2:$G$11))',
])

# Efficiency comparison
pdf.ln(3)
pdf.h3('\u63a8\u5e7f\u6548\u7387\u5bf9\u6bd4\u6c47\u603b\u8868')
ed = [
    ['\u8bd5\u70b9\u57ce\u5e02', '\u63a8\u5e7f\u6548\u7387EI', '\u7b14\u5747\u4ea4\u6613\u989d', '\u7ea2\u5305\u62c9\u52a8', '\u5546\u6237\u8986\u76d6\u7387'],
    ['\u6df1\u5733', '2.66', '680', '1,250.0', '268.8'],
    ['\u82cf\u5dde', '2.21', '633', '1,127.3', '257.1'],
    ['\u96c4\u5b89\u65b0\u533a', '4.29', '818', '900.0', '285.7'],
    ['\u6210\u90fd', '2.12', '625', '1,309.5', '250.0'],
    ['\u5317\u4eac', '2.80', '653', '1,306.7', '271.4'],
    ['\u4e0a\u6d77', '2.45', '644', '1,310.3', '264.5'],
    ['\u5e7f\u5dde', '2.13', '622', '1,275.0', '241.7'],
    ['\u6d77\u5357', '2.65', '743', '812.5', '224.5'],
    ['\u957f\u6c99', '2.13', '615', '1,280.0', '233.3'],
    ['\u897f\u5b89', '2.07', '622', '1,000.0', '222.2'],
]
ew = [26, 32, 32, 30, 32]
pdf.table_header(ed[0], ew)
for r in ed[1:]:
    pdf.table_row(r, ew)
pdf.table_row(['\u5168\u8bd5\u70b9\u5e73\u5747', '2.45', '665', '1,167.1', '251.9'], ew, bold=True, highlight=True)

# ===================== SECTION 7 =====================
pdf.add_page()
pdf.h2('\u4e03\u3001\u9644\u5f55\uff1a\u5e38\u89c1\u95ee\u9898\uff08FAQ\uff09')

faqs = [
    ['Q1', '\u6570\u5b57\u4eba\u6c11\u5e01\u548c\u5fae\u4fe1\u652f\u4ed8\u3001\u652f\u4ed8\u5b9d\u6709\u4ec0\u4e48\u533a\u522b\uff1f',
     '\u6570\u5b57\u4eba\u6c11\u5e01\u662f\u592e\u884c\u53d1\u884c\u7684\u6cd5\u5b9a\u8d27\u5e01\uff08M0\uff09\uff0c\u7b49\u540c\u4e8e\u73b0\u91d1\uff0c\u5177\u6709\u6cd5\u507f\u6027\uff1b\u5fae\u4fe1/\u652f\u4ed8\u5b9d\u662f\u7b2c\u4e09\u65b9\u652f\u4ed8\u5de5\u5177\u3002\u6570\u5b57\u4eba\u6c11\u5e01\u4e0d\u8ba1\u5229\u606f\uff0c\u4e0d\u4f9d\u8d56\u94f6\u884c\u5361\uff0c\u652f\u6301\u53cc\u79bb\u7ebf\u652f\u4ed8\u3002'],
    ['Q2', '\u4f7f\u7528\u6570\u5b57\u4eba\u6c11\u5e01\u9700\u8981\u624b\u7eed\u8d39\u5417\uff1f',
     '\u4e2a\u4eba\u7528\u6237\u5151\u6362\u3001\u63d0\u73b0\u3001\u8f6c\u8d26\u3001\u652f\u4ed8\u5747\u514d\u6536\u624b\u7eed\u8d39\u3002\u5546\u6237\u6536\u6b3e\u4e5f\u6682\u4e0d\u6536\u53d6\u624b\u7eed\u8d39\u3002'],
    ['Q3', '\u6570\u5b57\u4eba\u6c11\u5e01\u6709\u5229\u606f\u5417\uff1f',
     '\u6ca1\u6709\u3002\u6570\u5b57\u4eba\u6c11\u5e01\u5b9a\u4f4d\u4e3aM0\uff08\u6d41\u901a\u4e2d\u73b0\u91d1\uff09\uff0c\u4e0d\u8ba1\u4ed8\u5229\u606f\uff0c\u4e0e\u7eb8\u5e01\u786c\u5e01\u4e00\u81f4\u3002'],
    ['Q4', '\u624b\u673a\u4e22\u4e86\u600e\u4e48\u529e\uff1f',
     '\u6570\u5b57\u4eba\u6c11\u5e01\u94b1\u5305\u652f\u6301\u6302\u5931\u548c\u51bb\u7ed3\u529f\u80fd\u3002\u6302\u5931\u540e\u8d44\u91d1\u4e0d\u4f1a\u4e22\u5931\uff0c\u53ef\u5230\u539f\u8fd0\u8425\u673a\u6784\u6062\u590d\u3002'],
    ['Q5', '\u53ef\u4ee5\u62d2\u6536\u6570\u5b57\u4eba\u6c11\u5e01\u5417\uff1f',
     '\u4e0d\u53ef\u4ee5\u3002\u6570\u5b57\u4eba\u6c11\u5e01\u662f\u6cd5\u5b9a\u8d27\u5e01\uff0c\u4efb\u4f55\u5355\u4f4d\u548c\u4e2a\u4eba\u4e0d\u5f97\u62d2\u6536\u3002'],
    ['Q6', '\u8001\u5e74\u4eba\u5982\u4f55\u4f7f\u7528\uff1f',
     '\u53ef\u4f7f\u7528\u786c\u94b1\u5305\uff08\u53ef\u89c6\u5361\u3001\u624b\u73af\u7b49\uff09\uff0c\u652f\u6301NFC\u78b0\u4e00\u78b0\u652f\u4ed8\u3002'],
    ['Q7', '\u5982\u4f55\u4fdd\u62a4\u4e2a\u4eba\u9690\u79c1\uff1f',
     '\u91c7\u7528\u201c\u53ef\u63a7\u533f\u540d\u201d\u539f\u5219\u2014\u2014\u5c0f\u989d\u4ea4\u6613\u533f\u540d\uff0c\u5927\u989d\u4ea4\u6613\u4f9d\u6cd5\u53ef\u8ffd\u6eaf\u3002\u592e\u884c\u4e0d\u638c\u63e1\u4e2a\u4eba\u4ea4\u6613\u660e\u7ec6\u3002'],
    ['Q8', '\u652f\u6301\u8de8\u5883\u4f7f\u7528\u5417\uff1f',
     '\u901a\u8fc7mBridge\u652f\u6301\u8de8\u5883\u6279\u53d1\u7aef\u7ed3\u7b97\uff0c\u96f6\u552e\u7aef\u8de8\u5883\u652f\u4ed8\u7a33\u6b65\u63a8\u8fdb\u8bd5\u70b9\u3002'],
]
qw = [12, 52, 126]
pdf.table_header(['\u7f16\u53f7', '\u5e38\u89c1\u95ee\u9898', '\u53c2\u8003\u89e3\u7b54'], qw)

for q in faqs:
    if pdf.get_y() > 230:
        pdf.add_page()
    pdf.set_text_color(30, 30, 30)
    # Calculate needed height
    ans_len = len(q[2])
    rh = max(14, ans_len // 48 * 4.5 + 10)
    y0 = pdf.get_y()
    x0 = pdf.get_x()

    pdf.set_font('NS', 'B', 8)
    pdf.multi_cell(qw[0], 5, q[0], 1, 'C')
    y1 = pdf.get_y()

    pdf.set_xy(x0 + qw[0], y0)
    pdf.set_font('NS', 'B', 7.5)
    pdf.multi_cell(qw[1], 4.5, q[1], 1, 'L')
    y2 = max(y1, pdf.get_y())

    pdf.set_xy(x0 + qw[0] + qw[1], y0)
    pdf.set_font('NS', '', 7.5)
    pdf.multi_cell(qw[2], 4.5, q[2], 1, 'L')
    y3 = max(y2, pdf.get_y())
    pdf.set_y(y3)

# Training notice
pdf.ln(6)
pdf.note_box('\u57f9\u8bad\u987b\u77e5', [
    '\u2022 \u672c\u8d44\u6599\u5e94\u7ed3\u5408\u6700\u65b0\u653f\u7b56\u6587\u4ef6\u548c\u592e\u884c\u516c\u544a\u8fdb\u884c\u66f4\u65b0\u3002',
    '\u2022 \u6570\u636e\u7edf\u8ba1\u516c\u5f0f\u5efa\u8bae\u5728 Excel \u4e2d\u5b9e\u64cd\u7ec3\u4e60\uff0c\u52a0\u6df1\u7406\u89e3\u3002',
    '\u2022 \u5982\u6709\u7591\u95ee\u8bf7\u8054\u7cfb\u91d1\u878d\u79d1\u6280\u57f9\u8bad\u4e2d\u5fc3\uff1afintrain@company.com',
])

pdf.ln(8)
pdf.set_font('NS', '', 9)
pdf.set_text_color(180, 180, 180)
pdf.cell(0, 6, '\u2014 \u5168\u6587\u5b8c \u2014', 0, 1, 'C')

# Save
out = 'digital_rmb_training_guide_58372.pdf'
pdf.output(out)
sz = os.path.getsize(out)
print(f'OK: {out} ({sz:,} bytes, {pdf.page_no()} pages)')
