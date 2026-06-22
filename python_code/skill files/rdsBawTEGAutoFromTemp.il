;; 05/28/2020, updated by yangj1, remove MB2 rectangle shapes when AddTSV is True
;; Add H5 with the same size as M1, for DRC, 06/12/2020
;; 07/02/2020, updated by yangj1, add ptype option, type1 = type1 pad size, type2 = type2 pad size


procedure(rdsBawPad(cellId  ResonatorType Xpad Ypad AddTSV ptype tsv3050  padSig extension sign dirc)
let((layers lyrOS H W pts ps en1  diamM1 diamM2 diamTV  m2Wid  m2Len mb1ShapeML betShapeML tsvShapeML mb2ShapeML
	 shp mbebBox padLen  X1 Y1 _ver  polyLayer polyPad
	padLeft padRight padMid padTop padBot padRot deltaX deltaY X Y )
	
;; Pad master

	/*if(ptype == "TYPE2" then
		ps = 75.0; base size on Pad
	else
		ps = 95.0
	)
	*/
	case(ptype
			("TYPE1" ps = 95.0  )
			("TYPE2" ps = 75.0  )
			("TYPE3" ps = 63.0  )
	);;case
	
	deltaX = 0.5*ps; Frame origin to ll pad X
	deltaY = 0.5*ps; Frome origin to ll pad Y

	
	layers  = list( "BAW_MBE" "BAW_M1" "BAW_H5" "BAW_SV" "BAW_ReF"        ) ;; Layers need to build the pad
	lyrOS   = list( -7.0       -4.0     -4.0	-4.0     0.0   0.0)  ;; Layer Over Sizes
	if( ResonatorType == "series" then
		layers = append(layers list("BAW_TFP") )
	else
		layers = append(layers list("BAW_TFS") )
	)
;;
;; Drawing pad
;;
	X = Xpad + deltaX
	Y = Ypad + deltaY
	

	for(i 0 length(layers)-1
		H = 0.5*ps + nth(i lyrOS)
		W = 0.5*ps + nth(i lyrOS)
		if( sign == 1 then
			pts = list( -W+X:-H+Y -W+X:H+Y+extension W+X:H+Y+extension W+X:-H+Y )
		else
			if( sign == -1 then
				pts = list( -W+X:-H+Y-extension -W+X:H+Y W+X:H+Y W+X:-H+Y-extension )
			else
				pts = list( -W+X:-H+Y -W+X:H+Y W+X:H+Y W+X:-H+Y )
			)
		);;if
		
		polyLayer = nth(i layers)
		polyPad = dbCreatePolygon( cellId  polyLayer pts)
		
		if(polyLayer == "BAW_SV" && padSig == "G" then 
			dbCreateProp(polyPad "RDS_BAW_fTEG_G" 'boolean t)
			dbCreateLabel(cellId "text" X:Y "G" "centerCenter" "R0" "roman" 25)
			
			else
				if(polyLayer == "BAW_SV" && padSig == "S" then 
					dbCreateProp(polyPad "RDS_BAW_fTEG_S" 'boolean t)
					dbCreateLabel(cellId "text" X:Y "S" "centerCenter" "R0" "roman" 25)	
; add probe direction arrow line when signal pad
	                frameOff = 33.0; half of frame kpOut width
	                arrowW = 25.0; arrawXY	
;;	                if( ptype == "TYPE1" then fw=0.5*ps2+8.0  else fw=0.5*ps2+3.0 )
                    fw = 0.5*ps
	                if(dirc == "Left" then
	                     startx1=arrowW starty1=arrowW startx2=arrowW starty2=-arrowW startx3=6 starty3=0.5 startx4=fw starty4=1.0 startx5=startx4 starty5=-1.0  startx6=6 starty6=-0.5
	                else
	                    if(dirc == "Right" then
	                        startx1=-arrowW starty1=arrowW startx2=-arrowW starty2=-arrowW startx3=-6 starty3=0.5 startx4=-fw starty4=1.0 startx5=startx4 starty5=-1.0  startx6=-6 starty6=-0.5
	                    )
	                );;if
    		
		            triglist = list(startx1+X:starty1+Y X:Y startx2+X:starty2+Y)
		            traplist = list(startx3+X:starty3+Y startx4+X:starty4+Y startx5+X:starty5+Y startx6+X:starty6+Y)
		            dbCreatePath( cellId "BAW_LABEL" triglist 2.0)
		            dbCreatePolygon( cellId "BAW_LABEL" traplist )
		        );;if        
		);if		
    );;for


;; add TSV
        if( AddTSV=="Yes" then
        
;;		if(getShellEnvVar("RDS_CDS_VERIFY_TECH")== getShellEnvVar("RDS_CDS_TECH") then
			if(tsv3050 == "TSV30" then
				en1 = 25.0               ;; BET/MB1 enclosure by MB2, 15 with 50nm, 25 with 30nm
				diamM1 = 25.0            ;; BET/MB1 radium, 35 with 70nm, 25 with 50nm
				diamTV = 15.0            ;; TSV radium,  25 with 70nm, 15 with 50nm 			 
		 	 else 
	            en1 = 15.0               ;; BET/MB1 enclosure by MB2
        	    diamM1 = 35.0            ;; BET/MB1 radium
        	    diamTV = 25.0            ;; TSV radium   
			);if_tsv3050

			m2Wid = 150.0            ;; MB2 width
			m2Len = 100.0            ;; MB2 length 
            
			mb1ShapeML = dbCreateEllipse( cellId "BAW_MB1" list(-diamM1+X:-diamM1+Y diamM1+X:diamM1+Y))
			betShapeML = dbCreateEllipse( cellId "BAW_BET" list(-diamM1+X:-diamM1+Y diamM1+X:diamM1+Y))
			tsvShapeML = dbCreateEllipse( cellId "BAW_TSV" list(-diamTV+X:-diamTV+Y diamTV+X:diamTV+Y)) 	
		
;;			mb2ShapeML = dbCreateRect( cellId "BAW_MB2" list(-diamM1-en1+X:-diamM1-en1+Y m2Wid-diamM1-en1+X:diamM1+en1+Y) )
 	
    	);if_tsv    

;; add MB2
;        if( AddMB2=="Yes" then
;		diamM2 = 45.0            ;; MB2 radium 45
;		mb2ShapeML = dbCreateEllipse( cellId "BAW_MB2" list(-diamM2+X:-diamM2+Y diamM2+X:diamM2+Y))
;    	);if_mb2  
);let
);procedure 

procedure(rdsBawPadwMB2(cellId  ResonatorType Xpad Ypad AddTSV AddMB2 ptype tsv3050  padSig extension sign dirc)
let((layers lyrOS H W pts ps en1  diamM1 diamM2 diamTV  m2Wid  m2Len mb1ShapeML betShapeML tsvShapeML mb2ShapeML
	 shp mbebBox padLen  X1 Y1 _ver  polyLayer polyPad
	padLeft padRight padMid padTop padBot padRot deltaX deltaY X Y )
	
;; Pad master

	/*if(ptype == "TYPE2" then
		ps = 75.0; base size on Pad
	else
		ps = 95.0
	)
	*/
	case(ptype
			("TYPE1" ps = 95.0  )
			("TYPE2" ps = 75.0  )
			("TYPE3" ps = 63.0  )
	);;case
	
	deltaX = 0.5*ps; Frame origin to ll pad X
	deltaY = 0.5*ps; Frome origin to ll pad Y

	
	layers  = list( "BAW_MBE" "BAW_M1" "BAW_H5" "BAW_SV" "BAW_ReF"        ) ;; Layers need to build the pad
	lyrOS   = list( -7.0       -4.0     -4.0	-4.0     0.0   0.0)  ;; Layer Over Sizes
	if( ResonatorType == "series" then
		layers = append(layers list("BAW_TFP") )
	else
		layers = append(layers list("BAW_TFS") )
	)
;;
;; Drawing pad
;;
	X = Xpad + deltaX
	Y = Ypad + deltaY
	

	for(i 0 length(layers)-1
		H = 0.5*ps + nth(i lyrOS)
		W = 0.5*ps + nth(i lyrOS)
		if( sign == 1 then
			pts = list( -W+X:-H+Y -W+X:H+Y+extension W+X:H+Y+extension W+X:-H+Y )
		else
			if( sign == -1 then
				pts = list( -W+X:-H+Y-extension -W+X:H+Y W+X:H+Y W+X:-H+Y-extension )
			else
				pts = list( -W+X:-H+Y -W+X:H+Y W+X:H+Y W+X:-H+Y )
			)
		);;if
		
		polyLayer = nth(i layers)
		polyPad = dbCreatePolygon( cellId  polyLayer pts)
		
		if(polyLayer == "BAW_SV" && padSig == "G" then 
			dbCreateProp(polyPad "RDS_BAW_fTEG_G" 'boolean t)
			dbCreateLabel(cellId "text" X:Y "G" "centerCenter" "R0" "roman" 25)
			
			else
				if(polyLayer == "BAW_SV" && padSig == "S" then 
					dbCreateProp(polyPad "RDS_BAW_fTEG_S" 'boolean t)
					dbCreateLabel(cellId "text" X:Y "S" "centerCenter" "R0" "roman" 25)	
; add probe direction arrow line when signal pad
	                frameOff = 33.0; half of frame kpOut width
	                arrowW = 25.0; arrawXY	
;;	                if( ptype == "TYPE1" then fw=0.5*ps2+8.0  else fw=0.5*ps2+3.0 )
                    fw = 0.5*ps
	                if(dirc == "Left" then
	                     startx1=arrowW starty1=arrowW startx2=arrowW starty2=-arrowW startx3=6 starty3=0.5 startx4=fw starty4=1.0 startx5=startx4 starty5=-1.0  startx6=6 starty6=-0.5
	                else
	                    if(dirc == "Right" then
	                        startx1=-arrowW starty1=arrowW startx2=-arrowW starty2=-arrowW startx3=-6 starty3=0.5 startx4=-fw starty4=1.0 startx5=startx4 starty5=-1.0  startx6=-6 starty6=-0.5
	                    )
	                );;if
    		
		            triglist = list(startx1+X:starty1+Y X:Y startx2+X:starty2+Y)
		            traplist = list(startx3+X:starty3+Y startx4+X:starty4+Y startx5+X:starty5+Y startx6+X:starty6+Y)
		            dbCreatePath( cellId "BAW_LABEL" triglist 2.0)
		            dbCreatePolygon( cellId "BAW_LABEL" traplist )
		        );;if        
		);if		
    );;for


;; add TSV
        if( AddTSV=="Yes" then
        
;;		if(getShellEnvVar("RDS_CDS_VERIFY_TECH")== getShellEnvVar("RDS_CDS_TECH") then
			if(tsv3050 == "TSV30" then
				en1 = 25.0               ;; BET/MB1 enclosure by MB2, 15 with 50nm, 25 with 30nm
				diamM1 = 25.0            ;; BET/MB1 radium, 35 with 70nm, 25 with 50nm
				diamTV = 15.0            ;; TSV radium,  25 with 70nm, 15 with 50nm 			 
		 	 else 
	            en1 = 15.0               ;; BET/MB1 enclosure by MB2
        	    diamM1 = 35.0            ;; BET/MB1 radium
        	    diamTV = 25.0            ;; TSV radium   
			);if_tsv3050

			m2Wid = 150.0            ;; MB2 width
			m2Len = 100.0            ;; MB2 length 
            
			mb1ShapeML = dbCreateEllipse( cellId "BAW_MB1" list(-diamM1+X:-diamM1+Y diamM1+X:diamM1+Y))
			betShapeML = dbCreateEllipse( cellId "BAW_BET" list(-diamM1+X:-diamM1+Y diamM1+X:diamM1+Y))
			tsvShapeML = dbCreateEllipse( cellId "BAW_TSV" list(-diamTV+X:-diamTV+Y diamTV+X:diamTV+Y)) 	
		
;;			mb2ShapeML = dbCreateRect( cellId "BAW_MB2" list(-diamM1-en1+X:-diamM1-en1+Y m2Wid-diamM1-en1+X:diamM1+en1+Y) )
 	
    	);if_tsv    

;; add MB2
        if( AddMB2=="Yes" then
		diamM2 = 45.0            ;; MB2 radium 45
		mb2ShapeML = dbCreateEllipse( cellId "BAW_MB2" list(-diamM2+X:-diamM2+Y diamM2+X:diamM2+Y))
    	);if_mb2  
);let
);procedure 


procedure(rdsBawPadPc(cellId ResonatorType Xpad Ypad pc_type  padSig ps col FilpGnd2)
let((layers lyrOS H W shp polyLayer polyPad X Y pts i rdm)

	if(pc_type == "Probe_card_A" then
		rdm=15.0
	 else
		rdm=20.0
	);if


;; Pad master
;
	layers  = list( "BAW_MBE" "BAW_M1" "BAW_H5" "BAW_SV" "BAW_ReF" ) ;; Layers need to build the pad

	if(ADR == nil then
		lyrOS   = list( -7.0       -4.0     -4.0	-4.0     0.0   0.0)  ;; Layer Over Sizes
	else
		lyrOS   = list( -7.0       -5.0     -4.0	-4.0     0.0   0.0)  ;; Layer Over Sizes		
	);if

	if( ResonatorType == "series" then
		layers = append(layers list("BAW_TFP") )
	else
		layers = append(layers list("BAW_TFS") )
	);if
;;
;; Drawing pad
;;
	X = Xpad 
	Y = Ypad 

    for(i 0 length(layers)-1
		H = 0.5*ps + nth(i lyrOS)
		W = 0.5*ps + nth(i lyrOS)
		pts = list( -W+X:-H+Y -W+X:H+Y W+X:H+Y W+X:-H+Y )
		polyLayer = nth(i layers)
		polyPad = dbCreatePolygon( cellId  polyLayer pts)

/*		
		if( polyLayer == "BAW_MBE" then
			h2shp1  = dbCreatePolygon( cellId "BAW_H2" pts)
			h2shp2  = dbLayerSize( cellId "BAW_H2" list(h2shp1) -1.0)
			h2shp = dbLayerAndNot( cellId "BAW_H2"  list(h2shp1) h2shp2)
			h5shp = dbLayerAndNot( cellId "BAW_H5"  list(h2shp1) h2shp2)
			dbDeleteObject(h2shp1)
			foreach(ele h2shp2 dbDeleteObject(ele) )	
		);;if
*/		
		if(polyLayer == "BAW_SV" && padSig == "G" then 
			dbCreateProp(polyPad "RDS_BAW_fTEG_G" 'boolean t)
			dbCreateLabel(cellId "text" X:Y "G" "centerCenter" "R0" "roman" 25)
			bawDrawMidRect(cellId ResonatorType X Y ps col FilpGnd2)

			else
				if(polyLayer == "BAW_SV" && padSig == "S" then 
					dbCreateProp(polyPad "RDS_BAW_fTEG_S" 'boolean t)
					dbCreateLabel(cellId "text" X:Y "S" "centerCenter" "R0" "roman" 25)
					dbCreateEllipse(cellId "BAW_LABEL" list(X-rdm:Y-rdm X+rdm:Y+rdm))	
		        );;if        
		);if		
  	);;for

);let
);procedure 

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; generate middle rectangle connection with M1/MBE/SV/M2 layer
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;    
procedure(bawDrawMidRect(cellId ResonatorType X Y ps col FilpGnd2)
let((ccW rectW svOvl m2Ovl btOvl xfOvl layers lyrOS x1 x2 ext CCShape)

		ext = 11.5
		ccW  = 36.0             ;; width of connection part between two signal pads
		gndW = 120.0			;; right hand side wide gnd wire width of M1 layer
		rectW = 165.0			;; middle rectangle length of M1 layer
                 
		svOvl = 1.0         ;; R.SV.E.M1.B Min enclosure of M1 by SV on pad, SV layer is 1 um oversized M1
		m2Ovl = 1.0         ;; R.M1.E.M2 Min enclosure M2 by M1, M2 layer is 1 um inside of M1
		btOvl = 2.0         ;; R.M1.E.MBE.B  Min enclosure of MBE by M1 on frame and pad,  MBE layer is 2 um inside of M1 
		xfOvl = 5.0         ;; R.XeF.E.M1, min enclosure of M1 by XeF on pad and frame

		CCShape = nil
 	
		layers  = list( "BAW_M2" "BAW_SV" "BAW_ReF"  ) ;; Layers need to build the pad
		lyrOS   = list(   -1.0    0.0        4.0     4.0)  ;; Layer Over Sizes
		
		if( ResonatorType == "series" then
			layers = append(layers list("BAW_TFP") )
		else
			layers = append(layers list("BAW_TFS") )
		)        
	if(ADR == nil then
		if( col == 1 then 
			when(FilpGnd2==nil
	       			x1 = X-ps/2.0+xfOvl;
				x2 = x1-rectW
				y1 = Y-xfOvl
				y2 = y1+ccW 
				bBoxCC = list(x1-1.0:y1-1.0+ext x2-1.0:y2+1.0+ext)  
				bBoxBT = list(x1+btOvl:y1+btOvl+ext x2-btOvl:y2-btOvl+ext))
			when(FilpGnd2
	       			x1 = X+ps/2.0-xfOvl
				x2 = x1+rectW
				y1 = Y-xfOvl
				y2 = y1+ccW 
				bBoxCC = list(x1+1.0:y1-1.0+ext x2+1.0:y2+1.0+ext)  ;; center connection bBox for M1 layer
				bBoxBT = list(x1-btOvl:y1+btOvl+ext x2+btOvl:y2-btOvl+ext)) ;; center connection bBox for MBE layer 		
		else  
       			x1 = X+ps/2.0-xfOvl
			x2 = x1+rectW			
			y1 = Y-ps/2.0+xfOvl  
			y2 = y1+ccW  
			bBoxCC = list(x1+1.0:y1-1.0 x2+1.0:y2+1.0)  ;; center connection bBox for M1 layer
			bBoxBT = list(x1-btOvl:y1+btOvl x2+btOvl:y2-btOvl) ;; center connection bBox for MBE layer
		)
	   else
		if( col == 1 then 
			when(FilpGnd2==nil
	       			x1 = X-ps/2.0+xfOvl;
				x2 = x1-rectW
				y1 = Y-xfOvl
				y2 = y1+ccW 
				bBoxCC = list(x1:y1+ext x2:y2+ext)  
				bBoxBT = list(x1+btOvl:y1+btOvl+ext x2-btOvl:y2-btOvl+ext))
			when(FilpGnd2
	       			x1 = X+ps/2.0-xfOvl
				x2 = x1+rectW
				y1 = Y-xfOvl
				y2 = y1+ccW 
				bBoxCC = list(x1:y1+ext x2:y2+ext)  ;; center connection bBox for M1 layer
				bBoxBT = list(x1-btOvl:y1+btOvl+ext x2+btOvl:y2-btOvl+ext)) ;; center connection bBox for MBE layer 		
		   else  
       			x1 = X+ps/2.0-xfOvl
			x2 = x1+rectW			
			y1 = Y-ps/2.0+xfOvl  
			y2 = y1+ccW  
			bBoxCC = list(x1:y1 x2:y2)  ;; center connection bBox for M1 layer
			bBoxBT = list(x1-btOvl:y1+btOvl x2+btOvl:y2-btOvl) ;; center connection bBox for MBE layer
		)
	);ifADR	
	
	
	 	CCShape = rodCreateRect( 
				       ?layer  	"BAW_M1"
				       ?cvId	cellId
				       ?bBox  	bBoxCC
                       ?elementsY 1
				       );;center connection between two signal pads of M1 layer 
		CCShape = list(CCShape) 
		
		CCShapeBT = rodCreateRect( 
				       ?layer  	"BAW_MBE"
				       ?cvId	cellId
				       ?bBox  	bBoxBT
                       		       ?elementsY 1
				       );;center connection between two signal pads of MBE layer   				       	

         	foreach( instCC CCShape
         		for(i 0 length(layers)-1
             	 	rodCreatePolygon( 
				       ?layer      nth(i layers)
				       ?cvId	   cellId
                     		       ?fromObj    instCC
                       		       ?size       nth(i lyrOS)
				 );;rod
			);;for            			       
        );;foreach
))

procedure(rdsBawPadCir(cellId  ResonatorType Xpad Ypad AddTSV ptype tsv3050  padSig extension sign dirc probeDir ADR)
let((layers lyrOS H W pts ps en1  diamM1 diamM2 diamTV diamVSL m2Wid  m2Len mb1ShapeML betShapeML tsvShapeML mb2ShapeML vslShapeML
	 shp mbebBox padLen  X1 Y1 _ver  polyLayer polyPad
	padLeft padRight padMid padTop padBot padRot deltaX deltaY X Y rdm)
	
;; Pad master

	/*if(ptype == "TYPE2" then
		ps = 75.0; base size on Pad
	else
		ps = 95.0
	)
	*/
	case(ptype
			("TYPE1" ps = 95.0  )
			("TYPE2" ps = 75.0  )
			("TYPE3" ps = 63.0  )
	);;case
	rdm = 15.0 ; pcard A type

	deltaX = 0.5*ps; Frame origin to ll pad X
	deltaY = 0.5*ps; Frame origin to ll pad Y

	
	layers  = list( "BAW_MBE" "BAW_PZLneg" "BAW_M1" "BAW_H5" "BAW_SV" "BAW_ReF"        ) ;; Layers need to build the pad
;;	lyrOS   = list( -7.0       -4.0     -4.0	-4.0     0.0   0.0)  ;; Layer Over Sizes
	if(ADR then
	    lyrOS   = list( -7.0   -6.0        -5.0     -5.0	-5.0     0.0   0.0) 
	else
	    lyrOS   = list( -7.0   -6.0        -4.0     -4.0	-4.0     0.0   0.0) 
	);;if
	
	
	if( ResonatorType == "series" then
		layers = append(layers list("BAW_TFP") )
	else
		layers = append(layers list("BAW_TFS") )
	)
;;
;; Drawing pad
;;
	X = Xpad + deltaX
	Y = Ypad + deltaY
	

	for(i 0 length(layers)-1
		H = 0.5*ps + nth(i lyrOS)
		W = 0.5*ps + nth(i lyrOS)
		if( sign == 1 then
			pts = list( -W+X:-H+Y -W+X:H+Y+extension W+X:H+Y+extension W+X:-H+Y )			
		else
			if( sign == -1 then
				pts = list( -W+X:-H+Y-extension -W+X:H+Y W+X:H+Y W+X:-H+Y-extension )
			else
				pts = list( -W+X:-H+Y -W+X:H+Y W+X:H+Y W+X:-H+Y )
			)
		);;if
		
		polyLayer = nth(i layers)
		polyPad = dbCreatePolygon( cellId  polyLayer pts)
		
		;;add H2+H5 marker, mid pad has 1x1 marker, top/bottom pads will have 1xlonger marker
		mkl = ps-15.0
		mkw = ps+extension*abs(sign)-14.0-60.0
		if(mkw <= 1.0 then mkw = 1.0 )
	
		if(dirc == "Left" then
			mkbbx = list(-W+X+mkl:-0.5*mkw+0.5*extension*sign+Y -W+X+mkl+1.0:0.5*mkw+0.5*extension*sign+Y)
		else
		    if(dirc == "Right" then	
		    	mkbbx = list(-W+X:-0.5*mkw+0.5*extension*sign+Y -W+X+1.0:0.5*mkw+0.5*extension*sign+Y)
		    );;if		    
	    );;if
		if(polyLayer == "BAW_MBE" then
			dbCreateRect( cellId "BAW_H2" mkbbx)
			dbCreateRect( cellId "BAW_H5" mkbbx)
		)
		
		if(polyLayer == "BAW_SV" && padSig == "G" then 
			dbCreateProp(polyPad "RDS_BAW_fTEG_G" 'boolean t)
			dbCreateLabel(cellId "text" X:Y "G" "centerCenter" "R0" "roman" 25)
			
			else
				if(polyLayer == "BAW_SV" && padSig == "S" then 
					dbCreateProp(polyPad "RDS_BAW_fTEG_S" 'boolean t)
					dbCreateLabel(cellId "text" X:Y "S" "centerCenter" "R0" "roman" 25)	
		; add probe direction arrow line when signal pad
					frameOff = 33.0; half of frame kpOut width
					arrowW = 25.0; arrawXY	
		;;	                if( ptype == "TYPE1" then fw=0.5*ps2+8.0  else fw=0.5*ps2+3.0 )
				    fw = 0.5*ps
	    ;; add H2+H5 marker for DRC purpose
					;;mkl = fw-10.0
					;;mkw = 0.5
					;;mkX = X-3.0
					if(dirc == "Left" then
					     startx1=arrowW starty1=arrowW startx2=arrowW starty2=-arrowW startx3=6 starty3=0.5 startx4=fw starty4=1.0 startx5=startx4 starty5=-1.0  startx6=6 starty6=-0.5
					     ;;mkbbx = list(mkl-1.0+mkX:-mkw+Y mkl+mkX:mkw+Y)
					else
					    if(dirc == "Right" then
					        startx1=-arrowW starty1=arrowW startx2=-arrowW starty2=-arrowW startx3=-6 starty3=0.5 startx4=-fw starty4=1.0 startx5=startx4 starty5=-1.0  startx6=-6 starty6=-0.5
					        ;;mkbbx = list(-mkl+mkX:-mkw+Y -mkl+1.0+mkX:mkw+Y)
					    )
					);;if
					;;dbCreateRect( cellId "BAW_H2" mkbbx)
					;;dbCreateRect( cellId "BAW_H5" mkbbx)
					if(probeDir then	    		    
					    triglist = list(startx1+X:starty1+Y X:Y startx2+X:starty2+Y)
					    traplist = list(startx3+X:starty3+Y startx4+X:starty4+Y startx5+X:starty5+Y startx6+X:starty6+Y)
					    dbCreatePath( cellId "BAW_LABEL" triglist 2.0)
					    dbCreatePolygon( cellId "BAW_LABEL" traplist )
					 else
						dbCreateEllipse(cellId "BAW_LABEL" list(X-rdm:Y-rdm X+rdm:Y+rdm))
					);if

					);;if        
		);if		
    );;for



;; add TSV
        if( AddTSV=="Yes" then
        
;;		if(getShellEnvVar("RDS_CDS_VERIFY_TECH")== getShellEnvVar("RDS_CDS_TECH") then
			if(tsv3050 == "TSV30" then
				en1 = 25.0               ;; BET/MB1 enclosure by MB2, 15 with 50nm, 25 with 30nm
				diamM1 = 25.0            ;; BET/MB1 radium, 35 with 70nm, 25 with 50nm
		 		diamVSL = diamM1+3.0	 ;; VSL radium, over BET 3um
				diamTV = 15.0            ;; TSV radium,  25 with 70nm, 15 with 50nm 	
		 	 else 
	            en1 = 15.0               ;; BET/MB1 enclosure by MB2
        	    diamM1 = 35.0            ;; BET/MB1 radium
		    diamVSL = diamM1+3.0     ;; VSL radium, over BET 3um
        	    diamTV = 25.0            ;; TSV radium   
			);if_tsv3050

			m2Wid = 150.0            ;; MB2 width
			m2Len = 100.0            ;; MB2 length 
            
			mb1ShapeML = dbCreateEllipse( cellId "BAW_MB1" list(-diamM1+X:-diamM1+Y diamM1+X:diamM1+Y))
			betShapeML = dbCreateEllipse( cellId "BAW_BET" list(-diamM1+X:-diamM1+Y diamM1+X:diamM1+Y))
			vslShapeML = dbCreateEllipse( cellId "BAW_VSL" list(-diamVSL+X:-diamVSL+Y diamVSL+X:diamVSL+Y))
			tsvShapeML = dbCreateEllipse( cellId "BAW_TSV" list(-diamTV+X:-diamTV+Y diamTV+X:diamTV+Y)) 	
		
;;			mb2ShapeML = dbCreateRect( cellId "BAW_MB2" list(-diamM1-en1+X:-diamM1-en1+Y m2Wid-diamM1-en1+X:diamM1+en1+Y) )
 	
    	);if_tsv    

;; add MB2
;        if( AddMB2=="Yes" then
;		diamM2 = 45.0            ;; MB2 radium 45
;		mb2ShapeML = dbCreateEllipse( cellId "BAW_MB2" list(-diamM2+X:-diamM2+Y diamM2+X:diamM2+Y))
;    	);if_mb2  
);let
);procedure 


procedure(rdsBawPadPcLabel(cellId ResonatorType Xpad Ypad pc_type  padSig ps col FilpGnd2)
let((layers lyrOS H W shp polyLayer polyPad X Y pts i rdm)

	if(pc_type == "Probe_card_A" then
		rdm=15.0
	 else
		rdm=20.0
	);if


;; Pad master
;
	layers  = list( "BAW_MBE" "BAW_M1" "BAW_H5" "BAW_SV" "BAW_ReF" ) ;; Layers need to build the pad
	lyrOS   = list( -7.0       -4.0     -4.0	-4.0     0.0   0.0)  ;; Layer Over Sizes
	if( ResonatorType == "series" then
		layers = append(layers list("BAW_TFP") )
	else
		layers = append(layers list("BAW_TFS") )
	);if
;;
;; Drawing pad
;;
	X = Xpad 
	Y = Ypad 

	    for(i 0 length(layers)-1
		H = 0.5*ps + nth(i lyrOS)
		W = 0.5*ps + nth(i lyrOS)
		pts = list( -W+X:-H+Y -W+X:H+Y W+X:H+Y W+X:-H+Y )
		polyLayer = nth(i layers)
		polyPad = dbCreatePolygon( cellId  polyLayer pts)
		
		if(polyLayer == "BAW_SV" && padSig == "G" then 
			dbCreateProp(polyPad "RDS_BAW_fTEG_G" 'boolean t)
			dbCreateLabel(cellId "text" X:Y "G" "centerCenter" "R0" "roman" 25)
			bawDrawMidRect(cellId ResonatorType X Y ps col FilpGnd2)

			else
				if(polyLayer == "BAW_SV" && padSig == "S" then 
					dbCreateProp(polyPad "RDS_BAW_fTEG_S" 'boolean t)
					dbCreateLabel(cellId "text" X:Y "S" "centerCenter" "R0" "roman" 25)
					dbCreateEllipse(cellId "BAW_LABEL" list(X-rdm:Y-rdm X+rdm:Y+rdm))	
		        );;if        
		);if		
    	      );;for

);let
);procedure 


