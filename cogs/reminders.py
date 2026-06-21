from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from typing import Optional
from db import Session, Reminder
from utils import parse_duration, format_duration, reminder_embed_fields


class ReminderView(discord.ui.View):
    """Persistent view attached to each reminder message for quick Done/Snooze."""

    def __init__(self, reminder_id: int, bot: commands.Bot):
        super().__init__(timeout=None)
        self.reminder_id = reminder_id
        self.bot = bot

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="reminder_done")
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        with Session() as session:
            reminder = session.get(Reminder, self.reminder_id)
            if reminder is None or reminder.user_id != interaction.user.id:
                await interaction.response.send_message("Not your reminder.", ephemeral=True)
                return
            if reminder.completed:
                await interaction.response.send_message("Already marked done.", ephemeral=True)
                return
            reminder.completed = True
            session.commit()

        cog: RemindersCog = self.bot.get_cog("RemindersCog")
        if cog:
            cog.scheduler.remove_job(f"reminder_{self.reminder_id}", missing_ok=True)

        await interaction.response.edit_message(
            content=f"✅ Reminder **#{self.reminder_id}** marked as done!", view=None
        )

    @discord.ui.button(label="Snooze 1h", style=discord.ButtonStyle.secondary, custom_id="reminder_snooze")
    async def snooze_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        with Session() as session:
            reminder = session.get(Reminder, self.reminder_id)
            if reminder is None or reminder.user_id != interaction.user.id:
                await interaction.response.send_message("Not your reminder.", ephemeral=True)
                return
            if reminder.completed:
                await interaction.response.send_message("Reminder is already done.", ephemeral=True)
                return
            snooze_until = datetime.now(timezone.utc) + timedelta(hours=1)
            reminder.snoozed_until = snooze_until
            reminder.next_fire_at = snooze_until
            session.commit()
            reminder_id = reminder.id

        cog: RemindersCog = self.bot.get_cog("RemindersCog")
        if cog:
            cog.scheduler.reschedule_job(
                f"reminder_{reminder_id}",
                trigger="date",
                run_date=snooze_until,
            )

        await interaction.response.send_message(
            f"⏸ Snoozed for 1 hour. Next reminder <t:{int(snooze_until.timestamp())}:R>.",
            ephemeral=True,
        )


class RemindersCog(commands.Cog):
    def __init__(self, bot: commands.Bot, scheduler):
        self.bot = bot
        self.scheduler = scheduler

    remind_group = app_commands.Group(name="remind", description="Manage your persistent reminders")

    @remind_group.command(name="add", description="Create a new repeating reminder")
    @app_commands.describe(
        message="What to remind you about",
        interval="How often to repeat, e.g. 30m, 2h, 1d",
        start="When to first fire (optional), e.g. 'in 10m'. Defaults to immediately.",
    )
    async def remind_add(
        self,
        interaction: discord.Interaction,
        message: str,
        interval: str,
        start: Optional[str] = None,
    ):
        interval_secs = parse_duration(interval)
        if interval_secs is None:
            await interaction.response.send_message(
                "Could not parse interval. Try `30m`, `2h`, or `1d`.", ephemeral=True
            )
            return

        if start:
            # only support "in <duration>" for now
            if start.lower().startswith("in "):
                delay = parse_duration(start[3:])
            else:
                delay = parse_duration(start)
            if delay is None:
                await interaction.response.send_message(
                    "Could not parse start time. Try `in 10m` or leave blank.", ephemeral=True
                )
                return
            first_fire = datetime.now(timezone.utc) + timedelta(seconds=delay)
        else:
            first_fire = datetime.now(timezone.utc)

        with Session() as session:
            reminder = Reminder(
                user_id=interaction.user.id,
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                message=message,
                interval_seconds=interval_secs,
                next_fire_at=first_fire,
            )
            session.add(reminder)
            session.commit()
            reminder_id = reminder.id

        self._schedule_reminder(reminder_id, first_fire, interval_secs)

        ts = int(first_fire.timestamp())
        await interaction.response.send_message(
            f"⏰ Reminder **#{reminder_id}** created! First fire <t:{ts}:R>, every **{format_duration(interval_secs)}**.",
            ephemeral=True,
        )

    @remind_group.command(name="done", description="Mark a reminder as complete")
    @app_commands.describe(id="The reminder ID to complete")
    async def remind_done(self, interaction: discord.Interaction, id: int):
        with Session() as session:
            reminder = session.get(Reminder, id)
            if reminder is None or reminder.user_id != interaction.user.id:
                await interaction.response.send_message("Reminder not found.", ephemeral=True)
                return
            if reminder.completed:
                await interaction.response.send_message("Already completed.", ephemeral=True)
                return
            reminder.completed = True
            session.commit()

        self.scheduler.remove_job(f"reminder_{id}", missing_ok=True)
        await interaction.response.send_message(f"✅ Reminder **#{id}** done!", ephemeral=True)

    @remind_group.command(name="delete", description="Cancel a reminder without completing it")
    @app_commands.describe(id="The reminder ID to cancel")
    async def remind_delete(self, interaction: discord.Interaction, id: int):
        with Session() as session:
            reminder = session.get(Reminder, id)
            if reminder is None or reminder.user_id != interaction.user.id:
                await interaction.response.send_message("Reminder not found.", ephemeral=True)
                return
            session.delete(reminder)
            session.commit()

        self.scheduler.remove_job(f"reminder_{id}", missing_ok=True)
        await interaction.response.send_message(f"🗑 Reminder **#{id}** deleted.", ephemeral=True)

    @remind_group.command(name="list", description="List your active reminders")
    async def remind_list(self, interaction: discord.Interaction):
        with Session() as session:
            reminders = (
                session.query(Reminder)
                .filter_by(user_id=interaction.user.id, guild_id=interaction.guild_id, completed=False)
                .order_by(Reminder.id)
                .all()
            )

        if not reminders:
            await interaction.response.send_message("You have no active reminders.", ephemeral=True)
            return

        embed = discord.Embed(title="Your Active Reminders", color=discord.Color.blurple())
        for r in reminders:
            next_fire = r.next_fire_at
            if next_fire.tzinfo is None:
                next_fire = next_fire.replace(tzinfo=timezone.utc)
            ts = int(next_fire.timestamp())
            status = f"⏸ snoozed until <t:{ts}:R>" if r.snoozed_until else f"next <t:{ts}:R>"
            embed.add_field(
                name=f"#{r.id} — {r.message[:50]}",
                value=f"Every **{format_duration(r.interval_seconds)}** · fired {r.fire_count}× · {status}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remind_group.command(name="snooze", description="Pause a reminder for a duration")
    @app_commands.describe(id="The reminder ID to snooze", duration="How long to snooze, e.g. 1h, 2d")
    async def remind_snooze(self, interaction: discord.Interaction, id: int, duration: str):
        secs = parse_duration(duration)
        if secs is None:
            await interaction.response.send_message("Could not parse duration.", ephemeral=True)
            return

        with Session() as session:
            reminder = session.get(Reminder, id)
            if reminder is None or reminder.user_id != interaction.user.id:
                await interaction.response.send_message("Reminder not found.", ephemeral=True)
                return
            if reminder.completed:
                await interaction.response.send_message("Reminder is already done.", ephemeral=True)
                return
            snooze_until = datetime.now(timezone.utc) + timedelta(seconds=secs)
            reminder.snoozed_until = snooze_until
            reminder.next_fire_at = snooze_until
            session.commit()

        self.scheduler.reschedule_job(
            f"reminder_{id}",
            trigger="date",
            run_date=snooze_until,
        )

        ts = int(snooze_until.timestamp())
        await interaction.response.send_message(
            f"⏸ Reminder **#{id}** snoozed until <t:{ts}:R>.", ephemeral=True
        )

    @remind_group.command(name="edit", description="Edit an existing reminder")
    @app_commands.describe(
        id="The reminder ID to edit",
        message="New reminder text (optional)",
        interval="New repeat interval, e.g. 1h (optional)",
    )
    async def remind_edit(
        self,
        interaction: discord.Interaction,
        id: int,
        message: Optional[str] = None,
        interval: Optional[str] = None,
    ):
        if message is None and interval is None:
            await interaction.response.send_message("Provide at least one field to update.", ephemeral=True)
            return

        interval_secs = None
        if interval:
            interval_secs = parse_duration(interval)
            if interval_secs is None:
                await interaction.response.send_message("Could not parse interval.", ephemeral=True)
                return

        with Session() as session:
            reminder = session.get(Reminder, id)
            if reminder is None or reminder.user_id != interaction.user.id:
                await interaction.response.send_message("Reminder not found.", ephemeral=True)
                return
            if reminder.completed:
                await interaction.response.send_message("Cannot edit a completed reminder.", ephemeral=True)
                return
            if message:
                reminder.message = message
            if interval_secs:
                reminder.interval_seconds = interval_secs
                # reschedule from now with new interval
                next_fire = datetime.now(timezone.utc) + timedelta(seconds=interval_secs)
                reminder.next_fire_at = next_fire
                reminder.snoozed_until = None
                session.commit()
                self.scheduler.reschedule_job(
                    f"reminder_{id}",
                    trigger="interval",
                    seconds=interval_secs,
                    start_date=next_fire,
                )
            else:
                session.commit()

        await interaction.response.send_message(f"✏️ Reminder **#{id}** updated.", ephemeral=True)

    @remind_group.command(name="help", description="Show all reminder commands")
    async def remind_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="ReminderBot Help",
            description="The bot will @mention you on every interval until you mark the reminder done.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="/remind add",
            value=(
                "`message` — what to remind you about\n"
                "`interval` — how often to repeat: `30m`, `2h`, `1d`, `1w`\n"
                "`start` *(optional)* — delay before first fire: `in 10m`"
            ),
            inline=False,
        )
        embed.add_field(name="/remind list", value="Show all your active reminders.", inline=False)
        embed.add_field(name="/remind done <id>", value="Mark a reminder complete — stops all future fires.", inline=False)
        embed.add_field(name="/remind snooze <id> <duration>", value="Pause a reminder for a while, e.g. `1h`, `2d`.", inline=False)
        embed.add_field(name="/remind edit <id>", value="Update the `message` and/or `interval` of an existing reminder.", inline=False)
        embed.add_field(name="/remind delete <id>", value="Cancel a reminder without marking it done.", inline=False)
        embed.set_footer(text="Each reminder message also has Done and Snooze 1h buttons for quick actions.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _schedule_reminder(self, reminder_id: int, first_fire: datetime, interval_secs: int):
        self.scheduler.add_job(
            self._fire_reminder,
            trigger="interval",
            seconds=interval_secs,
            start_date=first_fire,
            id=f"reminder_{reminder_id}",
            args=[reminder_id],
            replace_existing=True,
        )

    async def _fire_reminder(self, reminder_id: int):
        with Session() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None or reminder.completed:
                self.scheduler.remove_job(f"reminder_{reminder_id}", missing_ok=True)
                return

            now = datetime.now(timezone.utc)

            # Respect snooze
            if reminder.snoozed_until:
                snoozed_until = reminder.snoozed_until
                if snoozed_until.tzinfo is None:
                    snoozed_until = snoozed_until.replace(tzinfo=timezone.utc)
                if now < snoozed_until:
                    return
                reminder.snoozed_until = None

            reminder.fire_count += 1
            reminder.next_fire_at = now + timedelta(seconds=reminder.interval_seconds)
            session.commit()

            user_id = reminder.user_id
            channel_id = reminder.channel_id
            msg = reminder.message
            count = reminder.fire_count
            rid = reminder.id

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        embed = discord.Embed(
            title="⏰ Reminder",
            description=msg,
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"Reminder #{rid} · fired {count}× · use /remind done {rid} to stop")

        view = ReminderView(rid, self.bot)
        await channel.send(content=f"<@{user_id}>", embed=embed, view=view)

    def restore_jobs(self):
        """Re-schedule all active reminders from the database on startup."""
        now = datetime.now(timezone.utc)
        with Session() as session:
            active = session.query(Reminder).filter_by(completed=False).all()
            for r in active:
                next_fire = r.next_fire_at
                if next_fire.tzinfo is None:
                    next_fire = next_fire.replace(tzinfo=timezone.utc)
                # If we missed fires while offline, fire immediately then resume interval
                fire_at = max(next_fire, now)
                self._schedule_reminder(r.id, fire_at, r.interval_seconds)
