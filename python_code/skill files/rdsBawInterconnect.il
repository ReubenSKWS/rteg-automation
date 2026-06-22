;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;; $Id: bawConnectResonators.il, v 1.0 2018/06/22 11:45:38 kotm Exp $
;; Revision 1.0 2018/06/22 11:45:38 kotm
;; "Initial Version"
;; Connect resonators 
;; To re-use this in Gen TEG utility, redefine rdsBawConnectLayers and rdsBawConnectLayers2
;; Add TF1~5 layers according to JH's requirement on 12/18/2018
;; 08/28/2019, updated by yangj1, customized interconnect utility
;;          enable instance level interconnect. Eg. in top cellview, select instances contains resonators/utility 
;;               generated resonators + MBE/MTE shapes to get interconnects
;;          no back up, no reverse function
;;          delete _connectMBE/MTE cells, interconnect are flattened
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

procedure( rdsBawInterconnect()
	let( 	(cv selSets selList instList instcv)
	;; Grab parametr from GUI
    cv = geGetEditCellView()	
    selSets = geGetSelSet()
    
    selList = list()
    instList = list()
    foreach( itm selSets
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && (itm~>layerName=="BAW_MTE" || itm~>layerName=="BAW_MBE" ) then
		 	selList = append(selList list(itm))
		 )
		 if( itm~>objType=="inst" && ( rexMatchp("^series$*" itm~>cellName) || rexMatchp("^shunt$*" itm~>cellName) || 
		 		rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_$*" itm~>cellName) ) then
		 	selList = append(selList list(itm))
		 )
		 if( itm~>objType=="inst" && (exists(x itm~>master~>instances~>cellName rexMatchp("^series$*" x)) || exists(x itm~>master~>instances~>cellName rexMatchp("^shunt$*" x)) || 
		 	exists(x itm~>master~>instances~>cellName rexMatchp("^Res_$*"  x))  || exists(x itm~>master~>instances~>cellName rexMatchp("$*_cres_$*"  x)) ) then 
		 	instList = append(instList list(itm))
		 )
		 
	);;foreach
	;; Call rdsBawConnectLayers2 with arguments
    rdsBawInterconnectLayers(cv selList)	
    foreach(inst instList
    	instcv = dbOpenCellViewByType(inst~>libName inst~>cellName "layout" "maskLayout" "a")
    	 allList = nconc(instcv~>shapes instcv~>instances) 
    	rdsBawInterconnectLayers(instcv allList)
    );;foreach
   );;let
);;proc


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;; $Id: rdsBawConnectLayers.il, v 1.0 2018/06/22 11:45:38 kotm Exp $
;; Revision 1.0 2018/06/22 11:45:38 kotm
;; "Initial Version"
;; Connect resonators 
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

procedure( rdsBawInterconnectLayers(cv selList)
     prog( ( cN lN vN ncv ncN ncN2 icv icv2 ;;userName idNum
	     layerList ovlList bkN bkcv zcN zcv
	     AA BB BBresized CC DD JJ KK blN blN2 pts pts2 ptsL ptsL2 
	     allCells allCN inst tmpName1 tmpName2 tmpName3 )

;	      cv = geGetEditCellView()
	      cN = cv~>cellName
	      lN = cv~>libName
	      vN = cv~>viewName

;	 selList = geGetSelSet()
	     blN = nil
	    blN2 = nil
	    ptsL = nil
	   ptsL2 = nil
	;;;;;;;;;;;;;To Get Connect Layer;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" then
		      blN = "MTE"
			else
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MBE" then
		     blN2 = "MBE"
		 );;if
		 );;if
	);;

	if( blN == nil && blN2 == nil then
	    rdsBasePopupMsg( "Nothing to generate. Please select BAW_MTE/BAW_MBE and resonators to generate connectors." )
	    return( nil )
	)

	;;;;;;;;;;;;;;;;To Remove existing Connect Cells if they are there;;;;;;;;;;;;;;;;;;;;;;;

	tmpName1 = sprintf(nil "%s_connectMTE" cN)
	tmpName2 = sprintf(nil "%s_connectMBE" cN)

	allCN    = nil	
	allCells = ddGetObj( lN )~>cells
	foreach( cell allCells
		 allCN = append1( allCN cell~>name )
	)

	foreach( inst cv~>instances
	    when( inst~>baseName=="myConnMTE" && inst~>cellName==tmpName1
	          dbDeleteObject( inst )
	          ddDeleteObj( ddGetObj( lN tmpName1 vN ) )
	    );;when
	    when( inst~>baseName=="myConnMBE" && inst~>cellName==tmpName2
	          dbDeleteObject( inst )
	          ddDeleteObj( ddGetObj( lN tmpName2 vN ) )
	    );;when
	);;foreach

	    when( member( tmpName1 allCN )
		  ddDeleteObj( ddGetObj( lN tmpName1 vN ) )
	    )
	    when( member( tmpName2 allCN )
		  ddDeleteObj( ddGetObj( lN tmpName2 vN ) )
	    )
	;;remove all cells with "connect" extensions
/*
	;;;;;;;;;;;;;;;To Keep Back up cell for MTE/MBE polygon;;;;;;;;;;;;;;;;;;;;
	;;bkN  = strcat("con" "_" userName "_" idNum "_backup")
	bkN  = strcat(cN "_connect_backup")
	bkcv = dbOpenCellViewByType( lN bkN vN "maskLayout" "w" )
	printf("Backup Cell Name = %s\n" bkN) 
	foreach( shp bkcv~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( itm selList 
		 ;if( ( itm~>objType=="polygon" && itm~>layerName=="BAW_MTE" ) ||
		 ;    ( itm~>objType=="polygon" && itm~>layerName=="BAW_MBE" )
		 ;    dbCopyFig( itm bkcv ) )
		 if( ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" ) ||
		     ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MBE" )
		     dbCopyFig( itm bkcv ) )
	);;foreach
	dbSave( bkcv )

;println("Check---A00")
*/


when( blN
	;;;;;;;;;;;;;To Create New Cell Based on Connect Layer;;;;;;;;;;;;;;;;;;;
	ptsL = nil
	ncN  = strcat(cN "_connectMTE" )
	ncv  = dbOpenCellViewByType( lN ncN vN "maskLayout" "s" )
	foreach( shp ncv~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( ins ncv~>instances dbDeleteObject(ins) ) ;; clean up before copy
	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" then
		     dbCopyFig( itm ncv )
		 );;if
		 if( itm~>objType=="inst" && ( rexMatchp("^series$*" itm~>cellName) || rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_$*" itm~>cellName) ) then
		     dbCopyFig( itm ncv )
		 );;if
		 if( itm~>objType=="inst" && ( rexMatchp("^shunt$*" itm~>cellName) || rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_$*" itm~>cellName)) then
		     dbCopyFig( itm ncv )
		 );;if
	);;foreach
	dbSave( ncv )
	icv=dbOpenCellViewByType( lN ncN vN "maskLayout" "a" )

	foreach( shape icv~>shapes 
		 if( ( shape~>objType=="polygon" || shape~>objType=="rect" ) &&
		     shape~>layerName=="BAW_MTE" then
			dbLayerSize( icv "BAW_KEY" list(shape) 0.0 )
			dbDeleteObject(shape)
		 )
	);;foreach
	foreach( inst icv~>instances
		 when( substring(inst~>cellName 1 6) =="series" ||  substring(inst~>cellName 1 5) =="shunt"  ||
		 		substring(inst~>cellName 1 4) =="Res_"  || rexMatchp("$*_cres_$*" inst~>cellName) 
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach


	foreach( shp icv~>shapes
		 unless( shp~>layerName=="BAW_MTE" || shp~>layerName=="BAW_KEY" 
			 || shp~>layerName=="BAW_H1" 
		 dbDeleteObject(shp)
		 )
	)

	BB=setof(shp icv~>shapes shp~>layerName=="BAW_MTE")
    ;; Shrink MTE of resonators -1um so that interconnect gets a 1um overlap with resonators
    BBresized = dbLayerSize(icv "BAW_MTE" BB -0.2)
	AA=setof(shp icv~>shapes shp~>layerName=="BAW_KEY")
	CC=setof(shp icv~>shapes shp~>layerName=="BAW_H1")
	DD=dbLayerSize(icv "pin" CC 1.0)
	KK=dbLayerAndNot(icv "BAW_MTE" AA BBresized 1024)
	JJ=dbLayerAndNot(icv "BAW_MTE" KK DD 1024)

	foreach(shp AA dbDeleteObject(shp) )	
	foreach(shp BB dbDeleteObject(shp) )	
    foreach(shp BBresized dbDeleteObject(shp) )
	foreach(shp CC dbDeleteObject(shp) )	
	foreach(shp DD dbDeleteObject(shp) )	
	foreach(shp KK dbDeleteObject(shp) )		
	
	;;;;;;;;;;;;;;;;;;;Layer Generation for the rest of the layers;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	layerList=list("BAW_STE" "BAW_PZL" "BAW_M1" "BAW_M2" "BAW_ReF" "BAW_SV" "BAW_TFP"  "BAW_TFS"   "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6"   "y2"  )
	ovlList  =list( 7.0       5.0       3.0      2.0      3.0       3.0       3.0         3.0          3.0       3.0      3.0       3.0	 3.0	   3.0       0.0  )

	for( j 0 length(layerList)-1
	     dbLayerSize(icv nth(j layerList) JJ nth(j ovlList) )
	)

;println("Check---A05")

	dbSave(icv)

	dbCreateInstByMasterName( cv lN ncN "layout" "myConnMTE" list(0 0) "R0" )

);;when


when( blN2
	;;;;;;;;;;;;;To Create New Cell Based on Connect Layer;;;;;;;;;;;;;;;;;;;
	;;ncN2 = strcat("conB" "_" userName "_" idNum)
	ncN2 = strcat(cN "_connectMBE")
	ncv2 = dbOpenCellViewByType( lN ncN2 vN "maskLayout" "s" )
	foreach( shp ncv2~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( ins ncv2~>instances dbDeleteObject(ins) ) ;; clean up before copy
	foreach( itm selList 
		 ;if( itm~>objType=="polygon" && itm~>layerName=="BAW_MBE" then
		 ;    dbCopyFig( itm ncv2 )
		 ;);;if
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MBE" then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && ( rexMatchp("^series$*" itm~>cellName) || rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_$*" itm~>cellName) ) then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && ( rexMatchp("^shunt$*" itm~>cellName) || rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_$*" itm~>cellName)) then
		     dbCopyFig( itm ncv2 )
		 );;if
	);;foreach
	dbSave( ncv2 )
	icv2=dbOpenCellViewByType( lN ncN2 vN "maskLayout" "a" )


	foreach( shape icv2~>shapes 
		 if( ( shape~>objType=="polygon" || shape~>objType=="rect" ) &&
		     shape~>layerName=="BAW_MBE" then
			dbLayerSize( icv2 "BAW_KEY" list(shape) 0.0 )
			dbDeleteObject(shape)
		 )
	);;foreach
	foreach( inst icv2~>instances
		 when( substring(inst~>cellName 1 6) =="series" ||  substring(inst~>cellName 1 5) =="shunt"  ||
		 		substring(inst~>cellName 1 4) =="Res_"  || rexMatchp("$*_cres_$*" inst~>cellName) 
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach


	foreach( shp icv2~>shapes
		 unless( shp~>layerName=="BAW_MBE" || shp~>layerName=="BAW_KEY" 
			 || shp~>layerName=="BAW_H1" 
		 dbDeleteObject(shp)
		 )
	)
	
	BB=setof(shp icv2~>shapes shp~>layerName=="BAW_MBE")
    ;; Shrink MBE of resonators -1um so that interconnect gets a 1um overlap with resonators
    BBresized = dbLayerSize(icv2 "BAW_MBE" BB -0.2)
	AA=setof(shp icv2~>shapes shp~>layerName=="BAW_KEY")
	CC=setof(shp icv2~>shapes shp~>layerName=="BAW_H1")
	DD=dbLayerSize(icv2 "pin" CC 1.0)
	KK=dbLayerAndNot(icv2 "BAW_MBE" AA BBresized 1024)
	JJ=dbLayerAndNot(icv2 "BAW_MBE" KK DD 1024)

	foreach(shp AA dbDeleteObject(shp) )	
	foreach(shp BB dbDeleteObject(shp) )	
    foreach(shp BBresized dbDeleteObject(shp) )	
	foreach(shp CC dbDeleteObject(shp) )	
	foreach(shp DD dbDeleteObject(shp) )	
	foreach(shp KK dbDeleteObject(shp) )	

	;;;;;;;;;;;;;;;;;;;Layer Generation for the rest of the layers;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	layerList=list("BAW_M1" "BAW_M2" "BAW_ReF" "BAW_SV" "BAW_TFP" "BAW_TFS"  "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6" )
	ovlList  =list( 3.0      2.0      3.0       3.0      3.0        3.0    	  3.0       3.0      3.0       3.0         3.0      3.0)

	for( i 0 length(layerList)-1
	     dbLayerSize(icv2 nth(i layerList) JJ nth(i ovlList) )
	)

;println("Check---B05")

	dbSave(icv2)

	dbCreateInstByMasterName( cv lN ncN2 "layout" "myConnMBE" list(0 0) "R0" )

);;when

;println("Check---C00")
	;;;;;;;;;;;;;;;;;;;Remove Polygons not needed ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) dbDeleteObject( itm ) )
	);;foreach

	;;;;;;;;;;;;;;;;;;;;;;;;;;;flatten interconnects;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
		
	myConnect = setof(x cv~>instances rexMatchp("_connectMBE" x~>cellName) || rexMatchp("_connectMTE" x~>cellName))
;;	dbFlattenInst( cv 1 nil )
	
	foreach(conn myConnect  dbFlattenInst( conn 1 nil )  )

	dbSave( cv )

	if( ddGetObj(lN  ncN2 vN) then  ddDeleteObj(ddGetObj(lN  ncN2 vN)))
    if( ddGetObj(lN  ncN vN)  then  ddDeleteObj(ddGetObj(lN  ncN vN)))
	
	return( t )

	);;prog

);;	



