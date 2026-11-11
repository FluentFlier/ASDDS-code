function result = plot_jetson_swarmsight(jetsonJson, swarmCsv, varargin)
%PLOT_JETSON_SWARMSIGHT Compare Jetson sleep bouts with SwarmSight motion.
%
% result = plot_jetson_swarmsight(jetsonJson, swarmCsv)
% result = plot_jetson_swarmsight(..., Name, Value)
%
% Required inputs
%   jetsonJson  JSON array containing start_time and end_time fields.
%   swarmCsv    SwarmSight CSV containing Frame and RightAngle columns.
%
% Name-value options
%   VideoStart             Datetime for video frame 1. If omitted, the
%                          function tries to read JL-YYMMDD-HHMMSS from the
%                          SwarmSight filename.
%   FrameRate              Source-video frames/second (default 5).
%   BinSeconds             Angular-speed bin width (default 10).
%   SmoothSeconds          Trailing smoothing window (default 120).
%   MinimumLowSeconds      Low activity must be strictly longer than this
%                          value (default 120).
%   SpeedCapPercentile     Winsorize frame-level angular speed at this
%                          percentile to limit tracker jumps (default 99).
%   LowActivityThreshold   Fixed threshold in degrees/second. Empty derives
%                          an exploratory Otsu threshold from this session.
%   Label                  Figure title. Empty uses the JSON filename.
%   OutputFile             Optional .png, .pdf, or other exportgraphics path.
%   Visible                Figure visibility, 'on' or 'off' (default 'on').
%
% The comparison uses only the right antenna. It wraps angle differences at
% +/-180 degrees, converts them to absolute angular speed, bins the result,
% applies a trailing average, and marks low-activity runs strictly longer
% than MinimumLowSeconds. The source JSON and CSV are read-only.

    parser = inputParser;
    parser.FunctionName = mfilename;
    addRequired(parser, 'jetsonJson', @isTextScalar);
    addRequired(parser, 'swarmCsv', @isTextScalar);
    addParameter(parser, 'VideoStart', NaT, @(x) isdatetime(x) && isscalar(x));
    addParameter(parser, 'FrameRate', 5, @(x) isnumeric(x) && isscalar(x) && x > 0);
    addParameter(parser, 'BinSeconds', 10, @(x) isnumeric(x) && isscalar(x) && x > 0);
    addParameter(parser, 'SmoothSeconds', 120, @(x) isnumeric(x) && isscalar(x) && x > 0);
    addParameter(parser, 'MinimumLowSeconds', 120, @(x) isnumeric(x) && isscalar(x) && x >= 0);
    addParameter(parser, 'SpeedCapPercentile', 99, @(x) isnumeric(x) && isscalar(x) && x > 0 && x <= 100);
    addParameter(parser, 'LowActivityThreshold', [], @(x) isempty(x) || (isnumeric(x) && isscalar(x) && isfinite(x) && x >= 0));
    addParameter(parser, 'Label', '', @isTextScalar);
    addParameter(parser, 'OutputFile', '', @isTextScalar);
    addParameter(parser, 'Visible', 'on', @(x) any(strcmpi(char(x), {'on', 'off'})));
    parse(parser, jetsonJson, swarmCsv, varargin{:});
    options = parser.Results;

    jetsonJson = char(jetsonJson);
    swarmCsv = char(swarmCsv);
    assert(isfile(jetsonJson), 'Jetson JSON not found: %s', jetsonJson);
    assert(isfile(swarmCsv), 'SwarmSight CSV not found: %s', swarmCsv);

    videoStart = options.VideoStart;
    if isnat(videoStart)
        videoStart = inferVideoStart(swarmCsv);
    end

    bouts = readJetsonBouts(jetsonJson);
    swarm = readSwarmSight(swarmCsv, videoStart, options.FrameRate);
    speedCap = percentileFinite(swarm.AbsoluteAngularSpeed, options.SpeedCapPercentile);
    cappedSpeed = min(swarm.AbsoluteAngularSpeed, speedCap);

    elapsed = seconds(swarm.Time - videoStart);
    finalSecond = max(elapsed);
    numberOfBins = max(1, ceil(finalSecond / options.BinSeconds));
    edges = (0:numberOfBins)' * options.BinSeconds;
    binIndex = discretize(elapsed, edges);
    binnedSpeed = groupedMean(binIndex, cappedSpeed, numberOfBins);
    binCenters = edges(1:end-1) + options.BinSeconds / 2;
    binTime = videoStart + seconds(binCenters);

    windowBins = max(1, ceil(options.SmoothSeconds / options.BinSeconds));
    smoothedSpeed = trailingCompleteMean(binnedSpeed, windowBins);
    if isempty(options.LowActivityThreshold)
        threshold = otsuThreshold(smoothedSpeed);
        thresholdSource = "Otsu threshold derived from this SwarmSight session";
    else
        threshold = double(options.LowActivityThreshold);
        thresholdSource = "User-supplied fixed threshold";
    end

    [lowState, lowIntervals] = strictLowRuns( ...
        smoothedSpeed < threshold, edges, videoStart, ...
        options.BinSeconds, options.MinimumLowSeconds);
    jetsonState = intervalsToState(bouts.StartTime, bouts.EndTime, binTime);
    valid = ~isnan(smoothedSpeed);
    metrics = comparisonMetrics(jetsonState(valid), lowState(valid));
    metrics.ThresholdDegPerSecond = threshold;
    metrics.SpeedCapDegPerSecond = speedCap;
    metrics.ValidBins = sum(valid);
    metrics.InputFrames = height(swarm);
    metrics.JetsonBoutCount = height(bouts);
    metrics.SwarmSightLowPeriodCount = height(lowIntervals);

    label = char(options.Label);
    if isempty(label)
        [~, label] = fileparts(jetsonJson);
    end
    fig = drawComparison(label, bouts, lowIntervals, binTime, binnedSpeed, ...
        smoothedSpeed, threshold, videoStart, videoStart + seconds(edges(end)), ...
        metrics, char(options.Visible));

    outputFile = char(options.OutputFile);
    if ~isempty(outputFile)
        outputFolder = fileparts(outputFile);
        if ~isempty(outputFolder) && ~isfolder(outputFolder)
            mkdir(outputFolder);
        end
        exportFigure(fig, outputFile);
    end

    trace = table(binTime, binnedSpeed, smoothedSpeed, jetsonState, lowState, ...
        'VariableNames', {'Time', 'BinnedAngularSpeed', 'SmoothedAngularSpeed', ...
        'JetsonSleep', 'SwarmSightLowActivity'});
    result = struct( ...
        'Figure', fig, ...
        'JetsonBouts', bouts, ...
        'SwarmSightLowActivity', lowIntervals, ...
        'Trace', trace, ...
        'Metrics', metrics, ...
        'VideoStart', videoStart, ...
        'FrameRate', options.FrameRate, ...
        'ThresholdSource', thresholdSource, ...
        'OutputFile', string(outputFile));
end


function tf = isTextScalar(value)
    tf = ischar(value) || (isstring(value) && isscalar(value));
end


function bouts = readJetsonBouts(path)
    records = jsondecode(fileread(path));
    if isempty(records)
        bouts = table(NaT(0, 1), NaT(0, 1), zeros(0, 1), ...
            'VariableNames', {'StartTime', 'EndTime', 'DurationSeconds'});
        return
    end
    required = {'start_time', 'end_time'};
    for i = 1:numel(required)
        assert(isfield(records, required{i}), ...
            'Jetson JSON is missing required field "%s".', required{i});
    end
    startTime = datetime(string({records.start_time})', ...
        'InputFormat', 'yyyy-MM-dd HH:mm:ss');
    endTime = datetime(string({records.end_time})', ...
        'InputFormat', 'yyyy-MM-dd HH:mm:ss');
    assert(all(~isnat(startTime)) && all(~isnat(endTime)), ...
        'Jetson timestamps must use yyyy-MM-dd HH:mm:ss.');
    assert(all(endTime >= startTime), 'A Jetson bout ends before it starts.');
    [startTime, order] = sort(startTime);
    endTime = endTime(order);
    durationSeconds = seconds(endTime - startTime);
    bouts = table(startTime, endTime, durationSeconds, ...
        'VariableNames', {'StartTime', 'EndTime', 'DurationSeconds'});
end


function swarm = readSwarmSight(path, videoStart, frameRate)
    try
        values = readtable(path, 'VariableNamingRule', 'preserve');
    catch
        values = readtable(path);
    end
    frameName = findColumn(values, 'Frame');
    angleName = findColumn(values, 'RightAngle');
    frame = numericColumn(values.(frameName));
    angle = numericColumn(values.(angleName));
    validFrame = isfinite(frame) & frame >= 1;
    frame = frame(validFrame);
    angle = angle(validFrame);
    [frame, order] = sort(frame);
    angle = angle(order);
    assert(~isempty(frame), 'SwarmSight CSV contains no valid frame numbers.');

    frameGap = [NaN; diff(frame)];
    angleChange = [NaN; diff(angle)];
    wrappedChange = mod(angleChange + 180, 360) - 180;
    absoluteAngularSpeed = abs(wrappedChange) ./ (frameGap / frameRate);
    absoluteAngularSpeed(frameGap <= 0) = NaN;
    time = videoStart + seconds((frame - 1) / frameRate);
    swarm = table(frame, time, angle, absoluteAngularSpeed, ...
        'VariableNames', {'Frame', 'Time', 'RightAngle', 'AbsoluteAngularSpeed'});
end


function name = findColumn(values, requested)
    names = string(values.Properties.VariableNames);
    normalized = lower(regexprep(names, '[^A-Za-z0-9]', ''));
    target = lower(regexprep(string(requested), '[^A-Za-z0-9]', ''));
    match = find(normalized == target, 1);
    assert(~isempty(match), 'SwarmSight CSV is missing column "%s".', requested);
    name = char(names(match));
end


function values = numericColumn(column)
    if isnumeric(column)
        values = double(column);
    else
        values = str2double(string(column));
    end
    values = values(:);
end


function startTime = inferVideoStart(path)
    [~, name] = fileparts(path);
    token = regexp(name, 'JL-(\d{6})-(\d{6})_Cam', 'tokens', 'once');
    assert(~isempty(token), [ ...
        'Could not infer frame-1 time from the SwarmSight filename. ' ...
        'Pass VideoStart explicitly, for example datetime(2026,7,21,18,2,19).']);
    startTime = datetime([token{1} token{2}], 'InputFormat', 'yyMMddHHmmss');
end


function result = groupedMean(group, values, numberOfGroups)
    valid = ~isnan(group) & isfinite(values);
    sums = accumarray(group(valid), values(valid), [numberOfGroups 1], @sum, 0);
    counts = accumarray(group(valid), 1, [numberOfGroups 1], @sum, 0);
    result = sums ./ counts;
    result(counts == 0) = NaN;
end


function result = trailingCompleteMean(values, width)
    result = movmean(values, [width - 1 0], 'omitnan');
    counts = movsum(~isnan(values), [width - 1 0]);
    result(counts < width) = NaN;
end


function value = percentileFinite(values, percentile)
    values = sort(values(isfinite(values)));
    assert(~isempty(values), 'RightAngle did not produce any valid angular speeds.');
    if numel(values) == 1
        value = values(1);
        return
    end
    position = 1 + (percentile / 100) * (numel(values) - 1);
    lowerIndex = floor(position);
    upperIndex = ceil(position);
    fraction = position - lowerIndex;
    value = values(lowerIndex) * (1 - fraction) + values(upperIndex) * fraction;
end


function threshold = otsuThreshold(values)
    values = values(isfinite(values));
    assert(~isempty(values), 'No finite smoothed angular speeds are available.');
    minimum = min(values);
    maximum = max(values);
    if maximum <= minimum
        threshold = minimum;
        return
    end
    numberOfBins = 256;
    edges = linspace(minimum, maximum, numberOfBins + 1);
    counts = histcounts(values, edges);
    centers = (edges(1:end-1) + edges(2:end)) / 2;
    totalCount = sum(counts);
    totalWeight = sum(counts .* centers);
    leftCount = 0;
    leftWeight = 0;
    bestScore = -Inf;
    threshold = centers(1);
    for i = 1:numberOfBins - 1
        leftCount = leftCount + counts(i);
        leftWeight = leftWeight + counts(i) * centers(i);
        rightCount = totalCount - leftCount;
        if leftCount == 0 || rightCount == 0
            continue
        end
        leftMean = leftWeight / leftCount;
        rightMean = (totalWeight - leftWeight) / rightCount;
        score = leftCount * rightCount * (leftMean - rightMean)^2;
        if score > bestScore
            bestScore = score;
            threshold = centers(i);
        end
    end
end


function [state, intervals] = strictLowRuns(candidate, edges, origin, binSeconds, minimumSeconds)
    candidate = candidate(:) & ~isnan(candidate(:));
    changes = diff([false; candidate; false]);
    runStarts = find(changes == 1);
    runEnds = find(changes == -1) - 1;
    keep = (runEnds - runStarts + 1) * binSeconds > minimumSeconds;
    runStarts = runStarts(keep);
    runEnds = runEnds(keep);
    state = false(size(candidate));
    for i = 1:numel(runStarts)
        state(runStarts(i):runEnds(i)) = true;
    end
    startTime = origin + seconds(edges(runStarts));
    endTime = origin + seconds(edges(runEnds + 1));
    durationSeconds = seconds(endTime - startTime);
    intervals = table(startTime, endTime, durationSeconds, ...
        'VariableNames', {'StartTime', 'EndTime', 'DurationSeconds'});
end


function state = intervalsToState(startTime, endTime, sampleTime)
    state = false(size(sampleTime));
    for i = 1:numel(startTime)
        state = state | (sampleTime >= startTime(i) & sampleTime < endTime(i));
    end
end


function metrics = comparisonMetrics(reference, candidate)
    reference = logical(reference(:));
    candidate = logical(candidate(:));
    truePositive = sum(reference & candidate);
    trueNegative = sum(~reference & ~candidate);
    falsePositive = sum(~reference & candidate);
    falseNegative = sum(reference & ~candidate);
    metrics = struct( ...
        'Agreement', safeDivide(truePositive + trueNegative, numel(reference)), ...
        'Sensitivity', safeDivide(truePositive, truePositive + falseNegative), ...
        'Specificity', safeDivide(trueNegative, trueNegative + falsePositive), ...
        'Precision', safeDivide(truePositive, truePositive + falsePositive), ...
        'Jaccard', safeDivide(truePositive, truePositive + falsePositive + falseNegative));
end


function value = safeDivide(numerator, denominator)
    if denominator == 0
        value = NaN;
    else
        value = numerator / denominator;
    end
end


function fig = drawComparison(label, bouts, lowIntervals, binTime, binnedSpeed, ...
        smoothedSpeed, threshold, rangeStart, rangeEnd, metrics, visible)
    colors = lines(3);
    jetsonColor = colors(1, :);
    swarmColor = colors(2, :);
    traceColor = colors(3, :);
    xStart = datenum(rangeStart);
    xEnd = datenum(rangeEnd);
    x = datenum(binTime);

    fig = figure('Color', 'w', 'Visible', visible, ...
        'Name', 'Jetson and SwarmSight comparison', ...
        'Position', [100 100 1250 780]);
    layout = tiledlayout(fig, 4, 1, 'TileSpacing', 'compact', 'Padding', 'compact');
    title(layout, sprintf('%s | Jetson-SwarmSight agreement %.1f%%', ...
        label, 100 * metrics.Agreement), 'Interpreter', 'none');

    jetsonAxis = nexttile(layout, 1);
    drawLane(jetsonAxis, bouts.StartTime, bouts.EndTime, xStart, xEnd, ...
        jetsonColor, 'Jetson sleep bouts');

    swarmAxis = nexttile(layout, 2);
    drawLane(swarmAxis, lowIntervals.StartTime, lowIntervals.EndTime, xStart, xEnd, ...
        swarmColor, 'SwarmSight right-antenna low activity');

    speedAxis = nexttile(layout, [2 1]);
    plot(speedAxis, x, binnedSpeed, 'Color', [0.72 0.72 0.72], 'LineWidth', 0.7, ...
        'DisplayName', '10-second mean');
    hold(speedAxis, 'on');
    plot(speedAxis, x, smoothedSpeed, 'Color', traceColor, 'LineWidth', 1.5, ...
        'DisplayName', 'Trailing mean');
    plot(speedAxis, [xStart xEnd], [threshold threshold], '--', ...
        'Color', swarmColor, 'LineWidth', 1.2, ...
        'DisplayName', sprintf('Low-activity threshold %.2f deg/s', threshold));
    hold(speedAxis, 'off');
    ylabel(speedAxis, '|angular velocity| (deg/s)');
    title(speedAxis, 'Right-antenna angular speed');
    grid(speedAxis, 'on');
    legend(speedAxis, 'Location', 'best');
    xlim(speedAxis, [xStart xEnd]);

    axesList = [jetsonAxis swarmAxis speedAxis];
    linkaxes(axesList, 'x');
    for i = 1:numel(axesList)
        xlim(axesList(i), [xStart xEnd]);
        axesList(i).Box = 'off';
    end
    jetsonAxis.XTickLabel = {};
    swarmAxis.XTickLabel = {};
    datetick(speedAxis, 'x', 'mmm dd HH:MM', 'keeplimits', 'keepticks');
    xlabel(speedAxis, 'Local experiment time');
end


function drawLane(axisHandle, startTime, endTime, xStart, xEnd, color, label)
    patch(axisHandle, [xStart xEnd xEnd xStart], [0 0 1 1], ...
        [0.94 0.94 0.94], 'EdgeColor', 'none');
    hold(axisHandle, 'on');
    for i = 1:numel(startTime)
        left = max(xStart, datenum(startTime(i)));
        right = min(xEnd, datenum(endTime(i)));
        if right > left
            patch(axisHandle, [left right right left], [0 0 1 1], color, ...
                'EdgeColor', 'none', 'FaceAlpha', 0.88);
        end
    end
    hold(axisHandle, 'off');
    xlim(axisHandle, [xStart xEnd]);
    ylim(axisHandle, [0 1]);
    axisHandle.YTick = 0.5;
    axisHandle.YTickLabel = {label};
    axisHandle.TickLength = [0 0];
end


function exportFigure(fig, outputFile)
    [~, ~, extension] = fileparts(outputFile);
    try
        if strcmpi(extension, '.pdf')
            exportgraphics(fig, outputFile, 'ContentType', 'vector');
        else
            exportgraphics(fig, outputFile, 'Resolution', 300);
        end
    catch
        if strcmpi(extension, '.pdf')
            print(fig, outputFile, '-dpdf', '-bestfit');
        else
            print(fig, outputFile, '-dpng', '-r300');
        end
    end
end
