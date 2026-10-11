"""
Interactive Discord UI for viewing and toggling scheduled routines.
"""

import logging
from typing import Optional

import discord

from app.scheduler.schedule_manager import SCHEDULE_DEFINITIONS, schedule_manager
from app.scheduler.scheduler_service import scheduler_service

logger = logging.getLogger(__name__)


def build_schedule_embed() -> discord.Embed:
    """Build a rich status embed displaying all 5 scheduled routines."""
    embed = discord.Embed(
        title="⏰ Autonomous Kitchen Schedules",
        description="Toggle automated routines or run them on demand.",
        color=discord.Color.blue(),
    )

    for job_id, meta in SCHEDULE_DEFINITIONS.items():
        enabled = schedule_manager.is_enabled(job_id)
        status_icon = "🟢 **ENABLED**" if enabled else "🔴 **PAUSED**"
        next_run = scheduler_service.get_job_next_run(job_id)
        next_run_str = f"\n• *Next Run*: `{next_run}`" if (enabled and next_run) else ""

        value = (
            f"**Status**: {status_icon}\n"
            f"• *Schedule*: `{meta.schedule_display}` (`{meta.cron}`)"
            f"{next_run_str}\n"
            f"• *Action*: {meta.description}"
        )
        embed.add_field(
            name=f"{meta.emoji} {meta.name}",
            value=value,
            inline=False,
        )

    embed.set_footer(text="Use the dropdown and buttons below to toggle routines or run them immediately.")
    return embed


class ScheduleSelect(discord.ui.Select):
    """Dropdown menu to select a routine."""

    def __init__(self, selected_job_id: Optional[str] = None):
        options = []
        for job_id, meta in SCHEDULE_DEFINITIONS.items():
            enabled = schedule_manager.is_enabled(job_id)
            status_indicator = "🟢" if enabled else "🔴"
            options.append(
                discord.SelectOption(
                    label=f"{status_indicator} {meta.name}",
                    value=job_id,
                    description=meta.schedule_display,
                    default=(job_id == selected_job_id),
                )
            )

        super().__init__(
            placeholder="Select a routine to configure or trigger...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view  # type: ignore
        view.selected_job_id = self.values[0]
        # Refresh view to update button labels / state
        view.update_components()
        await interaction.response.edit_message(embed=build_schedule_embed(), view=view)


class ScheduleManagementView(discord.ui.View):
    """
    Control panel view with dropdown selection and toggle/run buttons.
    """

    def __init__(self, selected_job_id: Optional[str] = "saturday_plan"):
        super().__init__(timeout=300)
        self.selected_job_id = selected_job_id or "saturday_plan"
        self.update_components()

    def update_components(self):
        """Rebuild components with updated states."""
        self.clear_items()
        self.add_item(ScheduleSelect(selected_job_id=self.selected_job_id))

        # Determine toggle button label and style based on selected job state
        is_selected_enabled = schedule_manager.is_enabled(self.selected_job_id)
        toggle_label = "Pause Routine" if is_selected_enabled else "Resume Routine"
        toggle_style = discord.ButtonStyle.danger if is_selected_enabled else discord.ButtonStyle.success

        toggle_btn = discord.ui.Button(
            label=toggle_label,
            style=toggle_style,
            custom_id="btn_toggle",
            row=1,
        )
        toggle_btn.callback = self.toggle_callback
        self.add_item(toggle_btn)

        run_now_btn = discord.ui.Button(
            label="▶ Run Now",
            style=discord.ButtonStyle.primary,
            custom_id="btn_run_now",
            row=1,
        )
        run_now_btn.callback = self.run_now_callback
        self.add_item(run_now_btn)

        refresh_btn = discord.ui.Button(
            label="🔄 Refresh",
            style=discord.ButtonStyle.secondary,
            custom_id="btn_refresh",
            row=1,
        )
        refresh_btn.callback = self.refresh_callback
        self.add_item(refresh_btn)

        enable_all_btn = discord.ui.Button(
            label="Enable All",
            style=discord.ButtonStyle.secondary,
            custom_id="btn_enable_all",
            row=2,
        )
        enable_all_btn.callback = self.enable_all_callback
        self.add_item(enable_all_btn)

        disable_all_btn = discord.ui.Button(
            label="Disable All",
            style=discord.ButtonStyle.secondary,
            custom_id="btn_disable_all",
            row=2,
        )
        disable_all_btn.callback = self.disable_all_callback
        self.add_item(disable_all_btn)

    async def toggle_callback(self, interaction: discord.Interaction):
        new_state = schedule_manager.toggle(self.selected_job_id)
        scheduler_service.sync_job_state(self.selected_job_id)
        meta = SCHEDULE_DEFINITIONS[self.selected_job_id]
        state_text = "resumed" if new_state else "paused"

        self.update_components()
        await interaction.response.edit_message(embed=build_schedule_embed(), view=self)
        await interaction.followup.send(
            f"✅ **{meta.name}** has been **{state_text}**.",
            ephemeral=True,
        )

    async def run_now_callback(self, interaction: discord.Interaction):
        meta = SCHEDULE_DEFINITIONS[self.selected_job_id]
        await interaction.response.send_message(
            f"⏳ Executing **{meta.name}** now in this channel...",
            ephemeral=True,
        )

        try:
            success = await scheduler_service.trigger_now(
                self.selected_job_id,
                bot=interaction.client,
                channel_id=interaction.channel_id,
            )
            if success:
                logger.info(f"Manual execution of '{self.selected_job_id}' completed.")
            else:
                await interaction.followup.send(
                    f"⚠️ Routine **{meta.name}** returned without dispatching (it may be paused).",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error(f"Error running routine '{self.selected_job_id}': {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error triggering {meta.name}: {e}", ephemeral=True)

    async def refresh_callback(self, interaction: discord.Interaction):
        self.update_components()
        await interaction.response.edit_message(embed=build_schedule_embed(), view=self)

    async def enable_all_callback(self, interaction: discord.Interaction):
        schedule_manager.set_all(True)
        for job_id in SCHEDULE_DEFINITIONS:
            scheduler_service.sync_job_state(job_id)
        self.update_components()
        await interaction.response.edit_message(embed=build_schedule_embed(), view=self)
        await interaction.followup.send("✅ All automated routines are now **Enabled**.", ephemeral=True)

    async def disable_all_callback(self, interaction: discord.Interaction):
        schedule_manager.set_all(False)
        for job_id in SCHEDULE_DEFINITIONS:
            scheduler_service.sync_job_state(job_id)
        self.update_components()
        await interaction.response.edit_message(embed=build_schedule_embed(), view=self)
        await interaction.followup.send("⏸️ All automated routines have been **Paused**.", ephemeral=True)
