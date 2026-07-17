from datetime import datetime  # for get_current_time and convert_to_pxdate_string
from pathlib import Path  # for write_output
from turtle import title  # for title case in map_title_to_pxfile
from typing import List, Dict  # for type hints

# from PxBuild.tests.controll.test_03024 import out_model # for testing purposes, to access the output model in pytest
from pxbuild.models.input.pydantic_pxmetadata import PxMetadata, AttachmentItem
from pxbuild.models.input.pydantic_pxbuildconfig import PxbuildConfig

from pxbuild.models.output.pxfile.px_file_model import PXFileModel

from .helpers.datadata_helpers.datadatasource import (
    Datadatasource,
)  # for accessing the data file specified in pxmetadata and using it in mapping
from .helpers.datadata_helpers.main_data import (
    MapData,
)  # for mapping the actual data values from the data file to the PX file model
from .helpers.loaded_jsons import LoadedJsons  # for loading and accessing the pxmetadata and config JSON files
from .helpers.support_files import (
    SupportFiles,
)  # for creating support files like the .vs file based on the pxmetadata and config

from pxbuild.models.middle.dims import (
    Dims,
)  # for accessing and working with dimensions in the pxmetadata, including coded and uncoded dimensions, time dimension, stub and heading

"""
This module contains the main class LoadFromPxmetadata, which is responsible for loading the pxmetadata and config files, mapping the metadata to the PX file model, and writing the output PX file.
"""


class LoadFromPxmetadata:
    """Main class for loading from pxmetadata and writing PX file."""

    LabelConstructionOptionDict = {
        "LabelConstructionOption.code": 0,
        "LabelConstructionOption.text": 1,
        "LabelConstructionOption.code_text": 2,
        "LabelConstructionOption.text_code": 3,
    }

    # PriceTypeDict = {"PriceType.current": "C", "PriceType.fixed": "F"} # for mapping price types from pxmetadata to the corresponding codes expected in the PX file

    def __init__(self, pxmetadata_id: str, config_file: str) -> None:
        """Initialize by loading pxmetadata and config, then map to PX file model."""
        self._pxmetadata_id = pxmetadata_id

        self._loaded_jsons: LoadedJsons = LoadedJsons(pxmetadata_id, config_file)

        self._config = self._loaded_jsons.get_config()
        self._pxmetadata_model = self._loaded_jsons.get_pxmetadata()

        self._datadata = Datadatasource(self._pxmetadata_model.dataset.data_file, self._config)

        self._dims = Dims(self._loaded_jsons, self._datadata)

        ##################
        self.models_for_pytest: dict = {}

        self._last_updated = self.get_last_updated(self._pxmetadata_model)

        out_model = PXFileModel()

        # loop in languages
        self._add_language_independent = True  # like AXIS_VERSION
        for language in self._config.admin.valid_languages:

            self._current_lang = language
            self._contact_string = self.get_contact_string(self._pxmetadata_model, language)

            self.map_pxbuildconfig_to_pxfile(self._config, language, out_model)
            self.map_pxmetadata_to_pxfile(self._pxmetadata_model, out_model)
            self.map_pxstatistics_to_pxfile(out_model)

            self.map_coded_dimensions_to_pxfile(out_model)
            self.map_dimensions_to_pxfile(out_model)
            self.map_measurements_to_pxfile(out_model)
            self.map_decimals_to_pxfile(out_model)
            self.map_time_dimension_to_pxfile(out_model)
            self.map_stub_heading_to_pxfile(out_model)
            self.map_title_to_pxfile(out_model)
            self.map_aggregallowed_to_pxfile(out_model)

            self.map_metaid_to_pxfile(out_model)
            self.map_cellnote_to_pxfile(out_model)

            fixdata = MapData(self._datadata, self._pxmetadata_model, self._config, self._dims, self._current_lang)
            fixdata.map_data(out_model)

            if not self._config.admin.build_multilingual_files:
                write_output(
                    self._pxmetadata_id, self._config.admin.output_destination.px_folder_format, out_model, language
                )

                self.models_for_pytest[language] = out_model
                out_model = PXFileModel()
            else:
                self._add_language_independent = False

        if self._config.admin.build_multilingual_files:
            write_output(self._pxmetadata_id, self._config.admin.output_destination.px_folder_format, out_model)
            self.models_for_pytest["multi"] = out_model

        support = SupportFiles(self._pxmetadata_model, self._config, self._dims, self._pxmetadata_id)
        support.make_vs_file()

    def _px_lang(self, lang: str) -> str | None:
        """
        Return None to emit untagged PX keywords when only one language is used.
        """
        single_lang = len(self._config.admin.valid_languages) == 1
        # If you are writing one file per language (not multilingual combined file),
        # and only one language exists, use untagged keywords.
        if single_lang and not self._config.admin.build_multilingual_files:
            return None
        return lang

    def map_metaid_to_pxfile(self, out_model: PXFileModel) -> None:
        """Map meta_id from pxmetadata to PX file, handling both language-independent and language-specific cases."""

        # Only set language-independent meta_id once (untagged), otherwise you get duplicate keys in multilingual files
        if self._add_language_independent:
            metaid_table: List[str] = []
            if self._pxmetadata_model.dataset.meta_id:
                metaid_table += self._pxmetadata_model.dataset.meta_id
            if metaid_table:
                out_model.meta_id.set(" ".join(metaid_table))

        # The rest of the meta_id fields are language-specific, so they go inside the language loop and get tagged with language.
        lang = self._current_lang
        if self._dims.coded_dimensions:
            for n_var in self._dims.coded_dimensions:
                my_var = n_var.get_pydantic()
                if my_var.meta_id:
                    out_model.meta_id.set(" ".join(my_var.meta_id), n_var.get_label(lang), None, lang)

        contdim = self._dims.contdim
        for my_cont in self._pxmetadata_model.dataset.measurements:
            if my_cont.meta_id:
                out_model.meta_id.set(
                    " ".join(my_cont.meta_id), contdim.get_label(lang), my_cont.label[self._current_lang], lang
                )

    def map_cellnote_to_pxfile(self, out_model: PXFileModel) -> None:
        """Map cell notes from pxmetadata to PX file, converting from code-based input to dimension-order and label-based output."""
        pxlang = self._px_lang(self._current_lang)
        if not self._pxmetadata_model.dataset.cell_notes:
            return
        lang = self._current_lang
        dimension_in_order = self._dims.get_dims_in_output_order()

        for cellnote in self._pxmetadata_model.dataset.cell_notes:
            # Convert code-based cell note attachments to dimension labels in output order
            valuecode_by_dimensioncode = self.get_valuecode_by_dimensioncode(cellnote.attachment)
            valuetexts_for_subkey: List[str] = []
            for dim in dimension_in_order:
                dimcode = dim.get_code()
                if dimcode in valuecode_by_dimensioncode:
                    valuecode = valuecode_by_dimensioncode[dimcode]
                    valuelabel = dim.get_valuelabel(lang, valuecode)
                    valuetexts_for_subkey.append(valuelabel)
                else:
                    valuetexts_for_subkey.append("*")  # Applies to all values of this dimension

            if cellnote.is_mandatory:
                out_model.cellnotex.set(cellnote.text[lang], valuetexts_for_subkey, pxlang)
            else:
                out_model.cellnote.set(cellnote.text[lang], valuetexts_for_subkey, pxlang)

    def get_valuecode_by_dimensioncode(self, attachments: List[AttachmentItem]) -> Dict[str, str]:
        """Helper function to convert list of AttachmentItem into a dictionary mapping dimension_code to value_code."""
        my_out: Dict[str, str] = {}
        for attachment in attachments:
            my_out[attachment.dimension_code] = attachment.value_code

        return my_out

    def map_aggregallowed_to_pxfile(self, out_model: PXFileModel) -> None:
        """Set AGGREGALLOWED to True if all measurements allow aggregation, otherwise False. Only set once for language-independent keywords."""
        # Check if all values in the array are True
        if self._add_language_independent:
            all_true = all(
                instance.aggregation_allowed for instance in self._pxmetadata_model.dataset.measurements
            )  # if any measurement does not allow aggregation, this will be False
            out_model.aggregallowed.set(all_true)

    def map_title_to_pxfile(self, out_model: PXFileModel) -> None:
        """Map title to PX file, using explicit title from pxmetadata if provided, otherwise auto-generating based on table_id, base_title, and dimension labels."""
        lang = self._current_lang
        model = self._pxmetadata_model.dataset
        pxlang = self._px_lang(lang)

        if model.title and model.title.get(lang):
            title = model.title[lang]
        else:
            tmp_list = self._dims.get_dimcodes_in_output_order()
            vari_list = self._dims.get_as_lables(tmp_list, lang)
            tmp_string = ", ".join(vari_list[:-1])
            title = (
                model.table_id
                + ": "
                + model.base_title[lang]
                + ", "
                + self._config.admin.the_word_by[lang]
                + " "
                + tmp_string
                + " "
                + self._config.admin.the_word_and[lang]
                + " "
                + vari_list[-1]
            )

        out_model.title.set(title, pxlang)

    def map_stub_heading_to_pxfile(self, out_model: PXFileModel) -> None:
        """Map stub and heading to PX file, handling both language-independent and language-specific cases."""
        lang = self._current_lang

        # Only set STUB/HEADING once (untagged), otherwise you get duplicate keys
        if not self._add_language_independent:
            return

        seen = False

        if self._dims.get_headingcodes():
            my_headings: List[str] = self._dims.get_as_lables(self._dims.get_headingcodes(), lang)
            out_model.heading.set(my_headings, None)  # untagged, set once
            seen = True

        if self._dims.get_stubcodes():
            my_stubs: List[str] = self._dims.get_as_lables(self._dims.get_stubcodes(), lang)
            out_model.stub.set(my_stubs, None)  # untagged, set once
            seen = True
        if not seen:
            raise Exception("Sorry, both stub and heading are empty.")

    def map_time_dimension_to_pxfile(self, out_model: PXFileModel) -> None:
        """Map time dimension to PX file, setting values, variablecode, variable_type
        and TIMEVAL (TLIST) based on the time dimension in pxmetadata."""
        time = self._dims.time
        lang = self._current_lang
        pxlang = self._px_lang(lang)

        out_model.values.set(time.get_labels(lang), time.get_label(lang), pxlang)
        out_model.variablecode.set(time.get_code(), time.get_label(lang), pxlang)
        out_model.variable_type.set(time.get_variabletype(), time.get_label(lang), pxlang)

        # TIMEVAL: derive the TLIST timescale from timePeriodFormat and list the periods.
        timescale = _tlist_timescale(self._pxmetadata_model.dataset.time_dimension.time_period_format)
        if timescale:
            out_model.timeval.set(timescale, time.get_codes(), time.get_label(lang), pxlang)

    def map_coded_dimensions_to_pxfile(self, out_model: PXFileModel) -> None:
        """Map coded dimensions to PX file, setting variablecode, variable_type, codes, values, domain, prestext, elimination,
        doublecolumn, and notes based on the coded dimensions in pxmetadata."""
        if self._dims.coded_dimensions:
            lang = self._current_lang
            pxlang = self._px_lang(lang)
            for n_var in self._dims.coded_dimensions:
                out_model.variablecode.set(n_var.get_code(), n_var.get_label(lang), pxlang)
                out_model.variable_type.set(n_var.get_variabletype(), n_var.get_label(lang), pxlang)
                out_model.codes.set(n_var.get_codes(lang), n_var.get_label(lang), pxlang)
                out_model.values.set(n_var.get_labels(lang), n_var.get_label(lang), pxlang)

                my_var = n_var.get_pydantic()  # to access the additional fields from the pydantic model of the variable
                my_funny_var_id = n_var.get_label(
                    lang
                )  # the variable label is used as the subkey for these additional fields in the PX file, and the language is specified for multilingual files

                if n_var.get_domain_literal():
                    # A literal domain pointer was supplied in the pxmetadata. Write it verbatim to DOMAIN,
                    # with no language suffix. Used when the value set is managed outside pxbuild (e.g. shared
                    # .vs/.agg sets referenced across tables).
                    out_model.domain.set(n_var.get_domain_literal(), my_funny_var_id, pxlang)
                elif n_var.groupings():
                    # If the coded dimension has groupings defined in the pxmetadata, set the domain in the PX file based on the domain ID from the pxmetadata for that dimension.
                    # This will link the variable to its corresponding domain in the output PX file, allowing for correct interpretation of the coded values based on the defined groupings.
                    out_model.domain.set(n_var.get_domain_id(lang), my_funny_var_id, pxlang)

                # The label construction option from the pxmetadata is mapped to the corresponding integer value expected in the PX file using the LabelConstructionOptionDict,
                # and set in the prestext field for the variable in the PX file, with the variable label as the subkey and language tagging for multilingual files.
                out_model.prestext.set(
                    self.LabelConstructionOptionDict[str(my_var.label_construction_option)], my_funny_var_id, pxlang
                )

                if not n_var.elimination_possible:
                    # If elimination is not possible for the coded dimension according to the pxmetadata, set the elimination field in the PX file to "NO" for that variable,
                    # with the variable label as the subkey and language tagging for multilingual files.
                    out_model.elimination.set("NO", my_funny_var_id, pxlang)
                else:
                    # If elimination is possible for the coded dimension, check if there is a specific elimination label provided in the pxmetadata.
                    # If there is, set the elimination field in the PX file to that label for the variable. If there is no specific label provided,
                    # set it to "YES" to indicate that elimination is possible, with the variable label as the subkey and language tagging for multilingual files.
                    label = n_var.get_elimination_label(lang)
                    if label:
                        out_model.elimination.set(label, my_funny_var_id, pxlang)
                    else:
                        out_model.elimination.set("YES", my_funny_var_id, pxlang)

                if my_var.doublecolumn:
                    # If the doublecolumn field is set to True for the coded dimension in the pxmetadata, set the doublecolumn field in the PX file to True for that variable,
                    # with the variable label as the subkey and language tagging for multilingual files. If it is not set to True, it will default to False in the PX file.
                    out_model.doublecolumn.set(my_var.doublecolumn, my_funny_var_id, pxlang)

                # Note on variable
                if my_var.notes:
                    for note in my_var.notes:
                        if note.is_mandatory:
                            out_model.notex.set(note.text[lang], my_funny_var_id, pxlang)
                        else:
                            out_model.note.set(note.text[lang], my_funny_var_id, pxlang)

                # Note on a value in variable
                my_value_notes = n_var.get_valuenotes()
                if my_value_notes:
                    for valuecode in my_value_notes:
                        for note in my_value_notes[valuecode]:
                            valuelabel = n_var.get_valuelabel(lang, valuecode)
                            if note.is_mandatory:
                                out_model.valuenotex.set(note.text[lang], n_var.get_label(lang), valuelabel, pxlang)
                            else:
                                out_model.valuenote.set(note.text[lang], n_var.get_label(lang), valuelabel, pxlang)

    def map_dimensions_to_pxfile(self, out_model: PXFileModel):
        """Map uncoded dimensions to PX file, setting variablecode, variable_type, and values based on the uncoded dimensions in pxmetadata."""
        if self._dims.dimensions:
            lang = self._current_lang
            pxlang = self._px_lang(lang)
            for n_var in self._dims.dimensions:

                out_model.variablecode.set(n_var.get_code(), n_var.get_label(lang), pxlang)
                out_model.variable_type.set(n_var.get_variabletype(), n_var.get_label(lang), pxlang)
                # For uncoded dimensions, only set values, not codes
                out_model.values.set(n_var.get_labels(lang), n_var.get_label(lang), pxlang)

                my_var = n_var.get_pydantic()
                my_funny_var_id = n_var.get_label(lang)

                if n_var.groupings():
                    out_model.domain.set(n_var.get_domain_id(lang), my_funny_var_id, pxlang)

                out_model.prestext.set(
                    self.LabelConstructionOptionDict[str(my_var.label_construction_option)], my_funny_var_id, pxlang
                )

                if not n_var.elimination_possible:
                    out_model.elimination.set("NO", my_funny_var_id, pxlang)
                else:
                    label = n_var.get_elimination_label(lang)
                    if label:
                        out_model.elimination.set(label, my_funny_var_id, pxlang)
                    else:
                        out_model.elimination.set("YES", my_funny_var_id, pxlang)

                if my_var.doublecolumn:
                    out_model.doublecolumn.set(my_var.doublecolumn, my_funny_var_id, pxlang)

                # Note on variable
                if my_var.notes:
                    for note in my_var.notes:
                        if note.is_mandatory:
                            out_model.notex.set(note.text[lang], my_funny_var_id, pxlang)
                        else:
                            out_model.note.set(note.text[lang], my_funny_var_id, pxlang)

                # Note on a value in variable
                my_value_notes = n_var.get_valuenotes()
                if my_value_notes:
                    for valuecode in my_value_notes:
                        for note in my_value_notes[valuecode]:
                            valuelabel = n_var.get_valuelabel(lang, valuecode)
                            if note.is_mandatory:
                                out_model.valuenotex.set(note.text[lang], n_var.get_label(lang), valuelabel, pxlang)
                            else:
                                out_model.valuenote.set(note.text[lang], n_var.get_label(lang), valuelabel, pxlang)

    def map_measurements_to_pxfile(self, out_model: PXFileModel):
        """Map measurements to PX file, setting seasadj, dayadj, units, precision, and notes based on the measurements in pxmetadata."""
        contdim = self._dims.contdim
        lang = self._current_lang
        pxlang = self._px_lang(lang)
        measurements = self._pxmetadata_model.dataset.measurements

        # Use explicit global units if provided, otherwise auto-generate.
        # For multi-content tables, use "flere".
        if self._pxmetadata_model.dataset.units and self._pxmetadata_model.dataset.units.get(lang):
            out_model.units.set(self._pxmetadata_model.dataset.units[lang], None, pxlang)
        elif len(measurements) > 1:
            out_model.units.set("flere", None, pxlang)
        else:
            only_unit = measurements[0].unit_of_measure[self._current_lang] if measurements else ""
            out_model.units.set(only_unit or "", None, pxlang)

        for my_cont in measurements:
            my_funny_cont_id = my_cont.label[self._current_lang]
            out_model.seasadj.set(my_cont.is_seasonally_adjusted or False, my_funny_cont_id, pxlang)
            out_model.dayadj.set(my_cont.is_workingdays_adjusted or False, my_funny_cont_id, pxlang)

            unit_text = my_cont.unit_of_measure[self._current_lang]
            if unit_text:
                out_model.units.set(unit_text, my_funny_cont_id, pxlang)

            if my_cont.precision is not None:
                out_model.precision.set(my_cont.precision, contdim.get_label(lang), my_funny_cont_id, pxlang)

            if my_cont.notes:
                for note in my_cont.notes:
                    if note.is_mandatory:
                        out_model.valuenotex.set(note.text[lang], contdim.get_label(lang), my_funny_cont_id, pxlang)
                    else:
                        out_model.valuenote.set(note.text[lang], contdim.get_label(lang), my_funny_cont_id, pxlang)

        out_model.values.set(contdim.get_labels(lang), contdim.get_label(lang), pxlang)
        out_model.codes.set(contdim.get_codes(), contdim.get_label(lang), pxlang)
        out_model.variablecode.set(contdim.get_code(), contdim.get_label(lang), pxlang)
        out_model.variable_type.set(contdim.get_variabletype(), contdim.get_label(lang), pxlang)

    def map_decimals_to_pxfile(self, out_model: PXFileModel):
        """Map decimals to PX file, setting decimals and showdecimals based on the dataset and measurements in pxmetadata."""
        if self._add_language_independent:
            # Use explicit decimals if provided, otherwise auto-generate based on the maximum of stored_decimals and show_decimals values from the measurements in pxmetadata,
            # to ensure that the decimals in the PX file are set to accommodate both the stored decimal precision and the display preferences for the measurements.
            if self._pxmetadata_model.dataset.decimals is not None:
                out_model.decimals.set(self._pxmetadata_model.dataset.decimals)
            else:
                show_decimals_values = [
                    instance.show_decimals
                    for instance in self._pxmetadata_model.dataset.measurements
                    if instance.show_decimals is not None
                ]

                if self._pxmetadata_model.dataset.stored_decimals:
                    out_model.decimals.set(
                        max(
                            self._pxmetadata_model.dataset.stored_decimals,
                            max(show_decimals_values) if show_decimals_values else 0,
                        )
                    )
                else:
                    out_model.decimals.set(max(show_decimals_values) if show_decimals_values else 0)

            # Use explicit showdecimals if provided, otherwise use min of measurement values
            if self._pxmetadata_model.dataset.show_decimals is not None:
                out_model.showdecimals.set(self._pxmetadata_model.dataset.show_decimals)
            else:
                show_decimals_values = [
                    instance.show_decimals
                    for instance in self._pxmetadata_model.dataset.measurements
                    if instance.show_decimals is not None
                ]
                if show_decimals_values:
                    out_model.showdecimals.set(min(show_decimals_values))

    def get_contact_string(self, in_data: PxMetadata, language: str) -> str:
        """Extract contact string from pxmetadata."""
        contact_string = ""

        if in_data.dataset.contacts is None:
            return contact_string

        for contact in in_data.dataset.contacts:
            # 'raw' is a verbatim passthrough (e.g. "Byrådsavdeling for finans (e@post)");
            # fall back to the structured name#phone#email form when raw is absent.
            if contact.raw and contact.raw.get(language):
                contact_string += f"{contact.raw[language]}##"
            elif contact.name is not None:
                contact_string += f"{contact.name.get(language, '')}#{contact.phone}#{contact.email}##"

        return contact_string[:-2]

    def get_last_updated(self, pxmetadata_model: PxMetadata) -> str:
        """Return the last updated date from metadata."""
        if pxmetadata_model.dataset.last_updated:
            try:
                return convert_to_pxdate_string(pxmetadata_model.dataset.last_updated, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return pxmetadata_model.dataset.last_updated

        last_updated_date = ""
        if pxmetadata_model.dataset.upcoming_releases is None:
            return last_updated_date

        if len(pxmetadata_model.dataset.upcoming_releases) < 1:
            return last_updated_date

        last_updated_date = pxmetadata_model.dataset.upcoming_releases[0]

        formatted_string = convert_to_pxdate_string(
            last_updated_date, pxmetadata_model.dataset.upcoming_releases_dateformat
        )

        return formatted_string

    def get_next_update(self) -> str:
        """Get next update date from pxmetadata."""
        last_updated_date = ""
        if self._pxmetadata_model.dataset.upcoming_releases is None:
            return last_updated_date

        if len(self._pxmetadata_model.dataset.upcoming_releases) < 2:
            return last_updated_date

        last_updated_date = self._pxmetadata_model.dataset.upcoming_releases[1]

        formatted_string = convert_to_pxdate_string(
            last_updated_date, self._pxmetadata_model.dataset.upcoming_releases_dateformat
        )

        return formatted_string

    def map_pxstatistics_to_pxfile(self, out_model: PXFileModel):
        """Map statistics-related fields from consolidated pxmetadata to PX file."""
        lang = self._current_lang
        pxlang = self._px_lang(lang)

        # Use explicit subjectarea from pxmetadata if provided, otherwise use subject_text
        if self._pxmetadata_model.dataset.subjectarea and self._pxmetadata_model.dataset.subjectarea.get(lang):
            out_model.subject_area.set(self._pxmetadata_model.dataset.subjectarea[lang], pxlang)
        elif self._pxmetadata_model.dataset.subject_text and self._pxmetadata_model.dataset.subject_text.get(lang):
            out_model.subject_area.set(self._pxmetadata_model.dataset.subject_text[lang], pxlang)

        if self._contact_string:
            out_model.contact.set(self._contact_string, None, pxlang)

        if self._add_language_independent:
            # Use explicit subject_code from pxmetadata
            if self._pxmetadata_model.dataset.subject_code:
                out_model.subject_code.set(self._pxmetadata_model.dataset.subject_code)

            if self._last_updated:
                out_model.last_updated.set(self._last_updated)

            next_update = self.get_next_update()
            if next_update:
                out_model.next_update.set(next_update)

            # UPDATE-FREQUENCY (language-independent) — read from the consolidated pxmetadata.
            update_frequency = self._pxmetadata_model.dataset.update_frequency
            if update_frequency and update_frequency.get(lang):
                out_model.update_frequency.set(update_frequency[lang])

    def map_pxmetadata_to_pxfile(self, in_model: PxMetadata, out_model: PXFileModel):
        """Map general metadata fields from pxmetadata to PX file, handling both language-independent and language-specific cases."""
        lang = self._current_lang
        if self._add_language_independent:
            out_model.tableid.set(in_model.dataset.table_id)
            # Use explicit matrix if provided, otherwise auto-generate
            if in_model.dataset.matrix:
                out_model.matrix.set(in_model.dataset.matrix)
            else:
                out_model.matrix.set("tab_" + in_model.dataset.table_id)
            if in_model.dataset.official_statistics:
                out_model.official_statistics.set(in_model.dataset.official_statistics)
            if in_model.dataset.copyright:
                out_model.copyright.set(in_model.dataset.copyright)
            if in_model.dataset.first_published:
                out_model.first_published.set(in_model.dataset.first_published)

            # The SYNONYMS keyword is language independent. So, all langs go into one for multilingual_files.
            temp_tags: List[str] = []
            if self._config.admin.build_multilingual_files:
                for language in self._config.admin.valid_languages:
                    temp_tags += in_model.dataset.search_keywords[language]
            else:
                temp_tags = in_model.dataset.search_keywords[lang]
            if temp_tags:
                out_model.synonyms.set(" ".join(temp_tags))

        lang = self._current_lang
        pxlang = self._px_lang(lang)
        # Use explicit contents if provided, otherwise auto-generate
        if in_model.dataset.contents and in_model.dataset.contents.get(lang):
            out_model.contents.set(in_model.dataset.contents[lang], pxlang)
        else:
            out_model.contents.set(in_model.dataset.table_id + ": " + in_model.dataset.base_title[lang] + ",", pxlang)
        if in_model.dataset.notes:
            for note in in_model.dataset.notes:
                if note.is_mandatory:
                    out_model.notex.set(note.text[lang], None, pxlang)
                else:
                    out_model.note.set(note.text[lang], None, pxlang)

    def map_pxbuildconfig_to_pxfile(self, in_config: PxbuildConfig, current_lang: str, out_model: PXFileModel):
        """Map general configuration fields from pxbuildconfig to PX file, handling both language-independent and language-specific cases."""
        pxlang = self._px_lang(current_lang)

        # Only set language-independent fields once (untagged), otherwise you get duplicate keys in multilingual files
        if self._add_language_independent:
            out_model.language.set(current_lang)
            if in_config.admin.build_multilingual_files:
                out_model.languages.set(in_config.admin.valid_languages)
            out_model.axis_version.set(str(in_config.axis_version))
            out_model.charset.set(str(in_config.charset))
            out_model.codepage.set(str(in_config.code_page))
            out_model.descriptiondefault.set((in_config.description_default or False))
            if not in_config.admin.skip_creation_date:
                out_model.creation_date.set(get_current_time())

        out_model.contvariable.set(str(in_config.contvariable[current_lang]), pxlang)

        # Use explicit datasymbols if provided, otherwise auto-generate
        if in_config.datasymbol1 and in_config.datasymbol1[self._current_lang]:
            out_model.datasymbol1.set(str(in_config.datasymbol1[self._current_lang]), pxlang)
        if in_config.datasymbol2 and in_config.datasymbol2[self._current_lang]:
            out_model.datasymbol2.set(str(in_config.datasymbol2[self._current_lang]), pxlang)
        if in_config.datasymbol3 and in_config.datasymbol3[self._current_lang]:
            out_model.datasymbol3.set(str(in_config.datasymbol3[self._current_lang]), pxlang)
        if in_config.datasymbol4 and in_config.datasymbol4[self._current_lang]:
            out_model.datasymbol4.set(str(in_config.datasymbol4[self._current_lang]), pxlang)
        if in_config.datasymbol5 and in_config.datasymbol5[self._current_lang]:
            out_model.datasymbol5.set(str(in_config.datasymbol5[self._current_lang]), pxlang)
        if in_config.datasymbol6 and in_config.datasymbol6[self._current_lang]:
            out_model.datasymbol6.set(str(in_config.datasymbol6[self._current_lang]), pxlang)
        if in_config.datasymbol_nil and in_config.datasymbol_nil[self._current_lang]:
            out_model.datasymbolnil.set(str(in_config.datasymbol_nil[self._current_lang]), pxlang)
        if in_config.datasymbol_sum and in_config.datasymbol_sum[self._current_lang]:
            out_model.datasymbolsum.set(str(in_config.datasymbol_sum[self._current_lang]), pxlang)

        # Use explicit dataset-level source if provided (per-table attribution,
        # e.g. NAV vs SSB), otherwise site-level source from pxbuildconfig
        dataset = self._pxmetadata_model.dataset
        if dataset.source and dataset.source.get(self._current_lang):
            out_model.source.set(dataset.source[self._current_lang], pxlang)
        else:
            out_model.source.set(in_config.source[self._current_lang], pxlang)


_TLIST_BY_FORMAT = {
    "åååå": "A1", "yyyy": "A1",
    "ååååHh": "H1",
    "ååååKk": "Q1", "ååååQq": "Q1",
    "ååååMmm": "M1", "ååååMm": "M1",
    "ååååUuu": "W1", "ååååWw": "W1",
    # Interval periods (school years "2011/2012", rolling windows "2007-2013"):
    # the PX spec has no interval timescale, so follow SCB's convention (e.g.
    # TAB5826): TLIST(A) without step digit, listing the period strings verbatim.
    "intervall": "A",
}


def _tlist_timescale(time_period_format: str) -> str:
    """Map a timePeriodFormat to a PX TLIST timescale (A1/H1/Q1/M1/W1, or A for
    interval periods). Returns None if no format is given. Falls back to token
    detection, then annual."""
    if not time_period_format:
        return None
    if time_period_format in _TLIST_BY_FORMAT:
        return _TLIST_BY_FORMAT[time_period_format]
    f = time_period_format.lower()
    if "u" in f or "w" in f:
        return "W1"
    if "m" in f:
        return "M1"
    if "k" in f or "q" in f:
        return "Q1"
    if "h" in f:
        return "H1"
    return "A1"


def convert_to_pxdate_string(date_string: str, date_format: str) -> str:
    """Convert a date string from a given format to the PX file format CCYYMMDD hh:mm."""
    dtm_date = datetime.strptime(date_string, date_format)
    px_date_string = dtm_date.strftime(f"%Y%m%d %H:%M")

    return px_date_string


def get_current_time() -> str:
    """
    Returns the current time as a string in the format CCYYMMDD hh:mm
    """
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d %H:%M")


def write_output(
    pxmetadata_id: str, px_folder_format: str, out_model: PXFileModel, language: str | None = None
) -> None:
    """Write the PX file output to the specified location, handling multilingual file naming if necessary."""
    temp_tabid = pxmetadata_id
    out_folder = px_folder_format.format(id=temp_tabid)
    language_part = ""
    if language:
        language_part = "_" + language

    out_file = f"{out_folder}/tab_{temp_tabid}{language_part}.px"
    Path(out_folder).mkdir(parents=True, exist_ok=True)

    with open(out_file, "w", encoding="cp1252", errors="replace") as f:
        print(out_model, file=f)

    print("File written to:", out_file)
