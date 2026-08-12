from django.core.management.base import BaseCommand
from django.utils import timezone
from shifts.models import Event, Notification
from accounts.models import Employee


class Command(BaseCommand):
    help = "Рассылка уведомлений сотрудникам о сегодняшних событиях с учетом их должностей"

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        
        # Находим сегодняшние события, по которым еще не отправляли уведомления
        events = Event.objects.filter(date=today, is_notification_sent=False).prefetch_related("target_positions")

        for event in events:
            # Получаем всех активных сотрудников организации
            employees = Employee.objects.filter(organization=event.organization, is_active=True)
            
            # Если у события заданы конкретные должности, фильтруем по ним
            target_positions = event.target_positions.all()
            if target_positions.exists():
                target_names = list(target_positions.values_list("name", flat=True))
                employees = employees.filter(position__in=target_names)

            # Создаем уведомления для каждого подходящего сотрудника
            for emp in employees:
                recipient_user = getattr(emp, "user", None)
                if recipient_user:
                    Notification.objects.create(
                        organization=event.organization,
                        recipient=recipient_user,
                        title=f"Событие: {event.title}",
                        message=f"На сегодня запланировано событие: {event.title}. {event.description}".strip(),
                        category=Notification.Category.SCHEDULE,
                        link="/shifts/schedule/",
                    )

            # Помечаем событие как обработанное
            event.is_notification_sent = True
            event.save()

        self.stdout.write(self.style.SUCCESS("Уведомления о событиях успешно разосланы!"))