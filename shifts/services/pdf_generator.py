"""PDF generation service for receipts and analytics reports."""

import io
import os
from datetime import datetime
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from shifts.models import PayrollAdjustment, PayrollPayment, Shift


class PDFReceiptService:
    """Сервис для генерации PDF-чеков о выплате зарплаты."""

    @staticmethod
    def _register_fonts():
        """Регистрирует шрифты для PDF."""
        font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
        font_bold_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf")

        font_name = "Arial"
        font_bold_name = "Arial-Bold"

        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
            except Exception:
                pass
        else:
            font_name = "Helvetica"

        if os.path.exists(font_bold_path):
            try:
                pdfmetrics.registerFont(TTFont(font_bold_name, font_bold_path))
            except Exception:
                pass
        else:
            font_bold_name = font_name

        return font_name, font_bold_name

    @staticmethod
    def generate_payment_receipt(payment):
        """Генерирует PDF-чек выплаты."""
        font_name, font_bold_name = PDFReceiptService._register_fonts()

        shifts = Shift.objects.filter(
            employee=payment.employee,
            status=Shift.Status.COMPLETED,
            opened_at__lte=payment.paid_at,
        ).order_by("-opened_at")[:10]

        adjustments = PayrollAdjustment.objects.filter(
            Q(payment=payment) | Q(employee=payment.employee, is_settled=True, created_at__lte=payment.paid_at)
        ).distinct()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        story = []
        styles = getSampleStyleSheet()

        style_title = ParagraphStyle(
            "DocTitle",
            fontName=font_bold_name,
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#111111"),
        )
        style_subtitle = ParagraphStyle(
            "DocSubtitle",
            fontName=font_name,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#666666"),
        )
        style_box_title = ParagraphStyle(
            "BoxTitle",
            fontName=font_bold_name,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748b"),
        )
        style_body = ParagraphStyle(
            "BodyTextCustom",
            fontName=font_name,
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#111111"),
        )
        style_body_bold = ParagraphStyle(
            "BodyBoldCustom",
            fontName=font_bold_name,
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#111111"),
        )
        style_amount_val = ParagraphStyle(
            "AmountVal",
            fontName=font_bold_name,
            fontSize=22,
            leading=26,
            alignment=1,
            textColor=colors.HexColor("#15803d"),
        )
        style_amount_lbl = ParagraphStyle(
            "AmountLbl",
            fontName=font_bold_name,
            fontSize=9,
            leading=12,
            alignment=1,
            textColor=colors.HexColor("#166534"),
        )
        style_th = ParagraphStyle(
            "TH",
            fontName=font_bold_name,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
        )
        style_td = ParagraphStyle(
            "TD",
            fontName=font_name,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#111111"),
        )
        style_td_right = ParagraphStyle(
            "TDRight",
            fontName=font_bold_name,
            fontSize=8.5,
            leading=11,
            alignment=2,
            textColor=colors.HexColor("#111111"),
        )
        style_footer = ParagraphStyle(
            "Footer",
            fontName=font_name,
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#94a3b8"),
            alignment=4,
        )

        # 1. Шапка
        header_left = [
            Paragraph(payment.organization.name, style_title),
            Paragraph("Официальный расчетный чек по заработной плате", style_subtitle),
        ]
        header_right = [
            Paragraph(
                f"Квитанция № {payment.id}",
                ParagraphStyle("HRight1", parent=style_body_bold, alignment=2),
            ),
            Paragraph(
                f"Дата: {payment.paid_at.strftime('%d.%m.%Y %H:%M')}",
                ParagraphStyle("HRight2", parent=style_subtitle, alignment=2),
            ),
        ]

        header_table = Table(
            [[header_left, header_right]], colWidths=[110 * mm, 70 * mm]
        )
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(header_table)
        story.append(
            HRFlowable(
                width="100%", thickness=2, color=colors.HexColor("#22c55e"), spaceAfter=12
            )
        )

        # 2. Инфо-блоки
        emp_pos = payment.employee.position or "Сотрудник"
        emp_freq = (
            payment.employee.get_payout_days_display()
            if hasattr(payment.employee, "get_payout_days_display")
            else "—"
        )
        creator = (
            payment.created_by.get_full_name() or payment.created_by.username
            if payment.created_by
            else "Администратор"
        )

        info_left = [
            Paragraph("СОТРУДНИК (ПОЛУЧАТЕЛЬ)", style_box_title),
            Spacer(1, 2 * mm),
            Paragraph(f"<b>{payment.employee.full_name}</b>", style_body),
            Paragraph(f"Должность: {emp_pos}", style_body),
            Paragraph(f"График выплат: {emp_freq}", style_body),
        ]

        info_right = [
            Paragraph("ВЫДАНО (РАБОТОДАТЕЛЬ)", style_box_title),
            Spacer(1, 2 * mm),
            Paragraph(f"Организация: {payment.organization.name}", style_body),
            Paragraph(f"Выдал: {creator}", style_body),
            Paragraph(
                f"Заметка: {payment.comment or 'Без комментариев'}", style_body
            ),
        ]

        box_table = Table([[info_left, info_right]], colWidths=[87 * mm, 87 * mm])
        box_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#e2e8f0")),
                    ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#e2e8f0")),
                    ("PADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(box_table)
        story.append(Spacer(1, 10))

        # 3. Сумма
        amount_content = [
            Paragraph("ВЫПЛАЧЕННАЯ СУММА", style_amount_lbl),
            Spacer(1, 2 * mm),
            Paragraph(f"{payment.amount} руб.", style_amount_val),
        ]
        amount_table = Table([[amount_content]], colWidths=[180 * mm])
        amount_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbf7d0")),
                    ("PADDING", (0, 0), (-1, -1), 10),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ]
            )
        )
        story.append(amount_table)
        story.append(Spacer(1, 12))

        # 4. Таблица смен
        story.append(Paragraph("<b>Отработанные смены в расчете:</b>", style_body))
        story.append(Spacer(1, 4))

        table_data = [
            [
                Paragraph("Дата смены", style_th),
                Paragraph("Время работы", style_th),
                Paragraph("Часы", style_th),
                Paragraph("Выручка", style_th),
                Paragraph("Начислено", ParagraphStyle("THRight", parent=style_th, alignment=2)),
            ]
        ]

        for shift_item in shifts:
            closed_str = (
                shift_item.closed_at.strftime("%H:%M") if shift_item.closed_at else "..."
            )
            time_str = f"{shift_item.opened_at.strftime('%H:%M')} — {closed_str}"
            sales_str = f"{shift_item.total_sales or Decimal('0.00')} руб."
            payout_str = f"{shift_item.calculated_payout or Decimal('0.00')} руб."

            table_data.append(
                [
                    Paragraph(shift_item.opened_at.strftime("%d.%m.%Y"), style_td),
                    Paragraph(time_str, style_td),
                    Paragraph(f"{shift_item.duration_hours} ч.", style_td),
                    Paragraph(sales_str, style_td),
                    Paragraph(payout_str, style_td_right),
                ]
            )

        if not shifts:
            table_data.append(
                [
                    Paragraph(
                        "Нет сведений о конкретных сменах",
                        ParagraphStyle("NoShifts", parent=style_td, alignment=1),
                    ),
                    "",
                    "",
                    "",
                    "",
                ]
            )

        shifts_table = Table(
            table_data, colWidths=[32 * mm, 42 * mm, 25 * mm, 43 * mm, 38 * mm]
        )
        shifts_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                    ("TOPPADDING", (0, 0), (-1, 0), 5),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        if not shifts:
            shifts_table.setStyle(TableStyle([("SPAN", (0, 1), (4, 1))]))

        story.append(shifts_table)

        # 5. Визуализация Премий и Штрафов
        if adjustments.exists():
            story.append(Spacer(1, 10))
            story.append(Paragraph("<b>Премии и удержания (штрафы):</b>", style_body))
            story.append(Spacer(1, 4))

            adj_data = [
                [
                    Paragraph("Тип", style_th),
                    Paragraph("Причина / Комментарий", style_th),
                    Paragraph("Дата", style_th),
                    Paragraph("Сумма", ParagraphStyle("THRight2", parent=style_th, alignment=2)),
                ]
            ]

            for adj in adjustments:
                is_bonus = adj.adjustment_type == PayrollAdjustment.AdjustmentType.BONUS
                sign = "+" if is_bonus else "-"
                amount_str = f"{sign}{adj.amount} руб."
                color_hex = "#15803d" if is_bonus else "#b91c1c"

                style_adj_val = ParagraphStyle(
                    "AdjVal", parent=style_td_right, textColor=colors.HexColor(color_hex)
                )

                adj_data.append(
                    [
                        Paragraph(adj.get_adjustment_type_display(), style_td),
                        Paragraph(adj.reason, style_td),
                        Paragraph(adj.created_at.strftime("%d.%m.%Y"), style_td),
                        Paragraph(amount_str, style_adj_val),
                    ]
                )

            adj_table = Table(adj_data, colWidths=[35 * mm, 80 * mm, 30 * mm, 35 * mm])
            adj_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(adj_table)

        story.append(Spacer(1, 20))

        # 6. Подписи
        sig_left = Paragraph(
            "Подпись сотрудника", ParagraphStyle("SigL", parent=style_body, alignment=1)
        )
        sig_right = Paragraph(
            "Подпись / Печать работодателя",
            ParagraphStyle("SigR", parent=style_body, alignment=1),
        )

        sig_table = Table([[sig_left, sig_right]], colWidths=[80 * mm, 80 * mm])
        sig_table.setStyle(
            TableStyle(
                [
                    ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.HexColor("#111111")),
                    ("LINEABOVE", (1, 0), (1, 0), 0.5, colors.HexColor("#111111")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(Spacer(1, 15))
        story.append(sig_table)
        story.append(Spacer(1, 15))

        footer_text = (
            f"Документ сформирован автоматически в CRM-системе easyCRM "
            f"{timezone.now().strftime('%d.%m.%Y %H:%M')}. "
            f"Электронный чек является подтверждением проведения денежной транзакции между работодателем и сотрудником."
        )
        story.append(
            HRFlowable(
                width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6
            )
        )
        story.append(Paragraph(footer_text, style_footer))

        doc.build(story)

        buffer.seek(0)
        filename = f"Receipt_PAY-{payment.id}_{payment.employee.last_name}.pdf"
        
        from django.http import HttpResponse
        response = HttpResponse(buffer.read(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class PDFAnalyticsService:
    """Сервис для генерации аналитических PDF-отчётов."""

    @staticmethod
    def _register_fonts():
        """Регистрирует шрифты для PDF."""
        font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
        font_bold_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf")

        font_name = "Arial"
        font_bold_name = "Arial-Bold"

        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
            except Exception:
                pass
        else:
            font_name = "Helvetica"

        if os.path.exists(font_bold_path):
            try:
                pdfmetrics.registerFont(TTFont(font_bold_name, font_bold_path))
            except Exception:
                pass
        else:
            font_bold_name = font_name

        return font_name, font_bold_name

    @staticmethod
    def generate_analytics_report(organization, period_mode):
        """Генерирует сводный аналитический PDF-отчёт за период."""
        from shifts.services import ShiftReportService

        font_name, font_bold_name = PDFAnalyticsService._register_fonts()

        today = timezone.localdate()
        start_date, end_date = ShiftReportService.get_date_range(period_mode)

        kpis = ShiftReportService.calculate_kpis(organization, start_date, end_date)
        total_revenue = kpis["total_revenue"]
        total_fot = kpis["total_fot"]
        fot_percentage = kpis["fot_percentage"]
        revenue_per_hour = kpis["revenue_per_hour"]
        completed_shifts = kpis["completed_shifts"]
        adjustments = kpis["adjustments"]

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        story = []
        style_title = ParagraphStyle(
            "Title",
            fontName=font_bold_name,
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#111111"),
        )
        style_subtitle = ParagraphStyle(
            "SubTitle",
            fontName=font_name,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#666666"),
        )
        style_box_lbl = ParagraphStyle(
            "BoxLbl",
            fontName=font_bold_name,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748b"),
        )
        style_box_val = ParagraphStyle(
            "BoxVal",
            fontName=font_bold_name,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#111111"),
        )
        style_th = ParagraphStyle(
            "TH",
            fontName=font_bold_name,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
        )
        style_td = ParagraphStyle(
            "TD",
            fontName=font_name,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#111111"),
        )
        style_td_bold = ParagraphStyle(
            "TDB",
            fontName=font_bold_name,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#111111"),
        )

        # Шапка
        header_left = [
            Paragraph(organization.name, style_title),
            Paragraph(
                f"Сводный финансово-аналитический отчёт ({start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')})",
                style_subtitle,
            ),
        ]
        header_right = [
            Paragraph(
                "easyCRM Analytics",
                ParagraphStyle(
                    "HR1", parent=style_subtitle, alignment=2, fontName=font_bold_name
                ),
            ),
            Paragraph(
                f"Сформирован: {timezone.now().strftime('%d.%m.%Y %H:%M')}",
                ParagraphStyle("HR2", parent=style_subtitle, alignment=2),
            ),
        ]

        header_table = Table(
            [[header_left, header_right]], colWidths=[110 * mm, 70 * mm]
        )
        header_table.setStyle(
            TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])
        )
        story.append(header_table)
        story.append(
            HRFlowable(
                width="100%", thickness=2, color=colors.HexColor("#facc15"), spaceAfter=12
            )
        )

        # Сводка KPI (4 карточки)
        kpi1 = [
            Paragraph("ВЫРУЧКА", style_box_lbl),
            Spacer(1, 1 * mm),
            Paragraph(f"{total_revenue} руб.", style_box_val),
        ]
        kpi2 = [
            Paragraph("ФОТ (ЗАРПЛАТЫ)", style_box_lbl),
            Spacer(1, 1 * mm),
            Paragraph(f"{total_fot} руб.", style_box_val),
        ]
        kpi3 = [
            Paragraph("ДОЛЯ ФОТ", style_box_lbl),
            Spacer(1, 1 * mm),
            Paragraph(f"{fot_percentage}%", style_box_val),
        ]
        kpi4 = [
            Paragraph("ВЫРУЧКА В ЧАС", style_box_lbl),
            Spacer(1, 1 * mm),
            Paragraph(f"{revenue_per_hour} руб.", style_box_val),
        ]

        kpi_table = Table(
            [[kpi1, kpi2, kpi3, kpi4]], colWidths=[43 * mm, 43 * mm, 43 * mm, 43 * mm]
        )
        kpi_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("PADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(kpi_table)
        story.append(Spacer(1, 14))

        # Таблица эффективности сотрудников
        story.append(Paragraph("<b>Результативность команды за период:</b>", style_td_bold))
        story.append(Spacer(1, 4))

        emp_data = [
            [
                Paragraph("Сотрудник", style_th),
                Paragraph("Смен / Часов", style_th),
                Paragraph("Выручка", style_th),
                Paragraph("ФОТ", style_th),
                Paragraph("Выручка/час", ParagraphStyle("TH2", parent=style_th, alignment=2)),
            ]
        ]

        employees = organization.employees.filter(is_active=True)
        employee_stats = ShiftReportService.get_employee_stats(
            employees, completed_shifts, adjustments, period_mode
        )

        for stat in employee_stats:
            emp = stat["employee"]
            emp_data.append(
                [
                    Paragraph(emp.full_name, style_td_bold),
                    Paragraph(
                        f"{stat['shifts_count']} смен ({stat['hours']} ч.)", style_td
                    ),
                    Paragraph(f"{stat['revenue']} руб.", style_td),
                    Paragraph(f"{stat['fot']} руб.", style_td),
                    Paragraph(
                        f"{stat['rev_per_hour']} руб./ч",
                        ParagraphStyle("TD2", parent=style_td, alignment=2),
                    ),
                ]
            )

        emp_table = Table(
            emp_data, colWidths=[45 * mm, 35 * mm, 35 * mm, 35 * mm, 30 * mm]
        )
        emp_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(emp_table)

        story.append(Spacer(1, 20))
        story.append(
            HRFlowable(
                width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6
            )
        )

        footer_text = (
            f"Документ сгенерирован автоматически в CRM-системе easyCRM. "
            f"Предназначен для управляющих и совладельцев организации {organization.name}."
        )
        story.append(
            Paragraph(
                footer_text,
                ParagraphStyle(
                    "Foot", fontName=font_name, fontSize=7.5, textColor=colors.HexColor("#94a3b8")
                ),
            )
        )

        doc.build(story)
        buffer.seek(0)

        filename = f"Analytics_Report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.pdf"
        
        from django.http import HttpResponse
        response = HttpResponse(buffer.read(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
