/*------------------------------------*/
//	Utilis - start.js
/*------------------------------------*/

jQuery(function ($) {
	// Validation groups
	$.utilis.addValidationGroupSupport();

	// Post buttons command/argument
	$.utilis.addPostCommandSupport();

	// Math.round(<number>, <decimals>)
	$.utilis.addBankersRoundingSupport();

	if ($.ui) {
		// jQuery UI defaults
		$.datepicker.setDefaults({
			constrainInput: false, // don't block key input
			showOtherMonths: true, // show days in prev/next months
			selectOtherMonths: true, // other months selectable
			showAnim: 'slideDown', // open with animation
			changeMonth: true, // combo month
			changeYear: true // combo year
		});

		// Disabe automatic overlay resizing
		$.ui.dialog.overlay.resize = $.noop;
		$.ui.dialog.overlay.width = function () { return ''; };
		$.ui.dialog.overlay.height = function () { return ''; };
	}

	// jQuery ajax setup
	$.ajaxSetup({
		cache: false, // Disable caching of AJAX responses 
		timeout: 360 * 1000 // 360 sec.
	});

	// Utilis unobtrusive
	var unobtrusiveInit = function (root) {
		var $el = $(root);

		if ($.ui) {
			// jquery.ui.datepicker
			var datepickers = $el.find('[data-u-datepicker="true"]');
			datepickers.datepicker();
			// jquery.tabs
			var tabs = $el.find('[data-u-tabs="true"]');
			tabs.tabs();
			// Buttons
			var buttons = $el.find(':submit, :button');
			buttons.button();
		}
		// jquery.upload
		var uploads = $el.find('[data-u-upload="true"]');
		uploads.upload();
		// jquery.grid
		var grids = $el.find('[data-u-grid="true"]');
		grids.grid();
		// jquery.grid2
		var grids2 = $el.find('[data-u-grid2="true"]');
		grids2.grid2();
		
		//after buttons!
		var sortgridbuttons = $el.find('[data-u-sortgridbutton="true"]');
		sortgridbuttons.sortgridbutton();

	};
	unobtrusiveInit(document);

	// Ajax on load, bind plugins
	$(document).on('loaded.ajax', function (e) {
		unobtrusiveInit(e.target);
	});

    // Fix autocomplete
	$(document).on('focus', ':input', function () {
	    $(this).attr('autocomplete', 'off');
	});
});