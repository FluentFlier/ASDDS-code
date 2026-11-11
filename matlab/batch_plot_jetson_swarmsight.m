function results = batch_plot_jetson_swarmsight(experiments, varargin)
%BATCH_PLOT_JETSON_SWARMSIGHT Plot one or more paired experiment files.
%
% experiments is a struct array or table with these fields/variables:
%   JetsonJson  required JSON path
%   SwarmCsv    required SwarmSight CSV path
%   VideoStart  optional datetime; filename inference is used when absent/NaT
%   FrameRate   optional source-video fps; default 5
%   Label       optional experiment label
%
% Name-value options:
%   OutputDir            output folder (default current folder)
%   OutputFormat         png or pdf (default png)
%   Visible              'on' or 'off' (default 'off')
%   LowActivityThreshold fixed deg/s threshold for all experiments; empty
%                        derives a separate exploratory threshold per file

% Example:
%   results = batch_plot_jetson_swarmsight(experiments, ...
%       'OutputDir', 'outputs/matlab_comparisons');

    parser = inputParser;
    addRequired(parser, 'experiments', @(x) isstruct(x) || istable(x));
    addParameter(parser, 'OutputDir', pwd, @(x) ischar(x) || isstring(x));
    addParameter(parser, 'OutputFormat', 'png', @(x) any(strcmpi(char(x), {'png', 'pdf'})));
    addParameter(parser, 'Visible', 'off', @(x) any(strcmpi(char(x), {'on', 'off'})));
    addParameter(parser, 'LowActivityThreshold', [], @(x) isempty(x) || (isnumeric(x) && isscalar(x) && x >= 0));
    parse(parser, experiments, varargin{:});
    options = parser.Results;

    if istable(experiments)
        experiments = table2struct(experiments);
    end
    assert(~isempty(experiments), 'At least one experiment is required.');
    assert(all(isfield(experiments, {'JetsonJson', 'SwarmCsv'})), ...
        'Each experiment needs JetsonJson and SwarmCsv fields.');
    outputDir = char(options.OutputDir);
    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    results = struct([]);
    for i = 1:numel(experiments)
        item = experiments(i);
        videoStart = optionalField(item, 'VideoStart', NaT);
        frameRate = optionalField(item, 'FrameRate', 5);
        label = char(optionalField(item, 'Label', sprintf('experiment_%02d', i)));
        safeLabel = regexprep(lower(label), '[^a-z0-9]+', '-');
        safeLabel = regexprep(safeLabel, '(^-|-$)', '');
        if isempty(safeLabel)
            safeLabel = sprintf('experiment-%02d', i);
        end
        outputFile = fullfile(outputDir, sprintf('%s-jetson-swarmsight.%s', ...
            safeLabel, lower(char(options.OutputFormat))));
        current = plot_jetson_swarmsight(item.JetsonJson, item.SwarmCsv, ...
            'VideoStart', videoStart, ...
            'FrameRate', frameRate, ...
            'Label', label, ...
            'LowActivityThreshold', options.LowActivityThreshold, ...
            'OutputFile', outputFile, ...
            'Visible', options.Visible);
        if isempty(results)
            results = repmat(current, numel(experiments), 1);
        else
            results(i) = current;
        end
    end
end


function value = optionalField(item, field, defaultValue)
    if isfield(item, field) && ~isempty(item.(field))
        value = item.(field);
    else
        value = defaultValue;
    end
end
